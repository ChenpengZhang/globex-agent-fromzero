import hashlib
import json
import logging
import uuid
from dataclasses import dataclass

from app.application.agents.orchestrator import SubmitIntentInput
from app.application.agents.session_registry import SessionOwnershipError
from app.application.events import EventPublisher, TradeEventType
from app.application.idempotency import IdempotencyStore
from app.domain.queue.ports.task_queue import IntentTask, TaskQueue, TaskStatus
from app.domain.session.ports.conversation_store import ConversationStore


logger = logging.getLogger(__name__)

_IDEMPOTENCY_TTL_SECONDS = 5 * 60


@dataclass(frozen=True)
class EnqueueIntentResult:
    task_id: str
    created: bool


class EnqueueIntentUseCase:
    """Validate ownership and submit one idempotent Agent task."""

    def __init__(
        self,
        task_queue: TaskQueue,
        idempotency: IdempotencyStore,
        conversation_store: ConversationStore,
        event_publisher: EventPublisher,
        *,
        priority_enabled: bool = True,
        large_request_turns: int = 30,
    ) -> None:
        self._task_queue = task_queue
        self._idempotency = idempotency
        self._conversation_store = conversation_store
        self._event_publisher = event_publisher
        self._priority_enabled = priority_enabled
        self._large_request_turns = large_request_turns

    async def execute(
        self,
        intent: SubmitIntentInput,
        idempotency_key: str | None = None,  # frontend request key
    ) -> EnqueueIntentResult:
        request_key = self._request_key(intent, idempotency_key)  # buyerid + frontend key
        proposed_task_id = f"task-{uuid.uuid4().hex[:12]}"  
        # create task id in advance
        # to avoid two requests querying backend cache at the same time
        # if not found request_key add immediately.
        claim = await self._idempotency.claim(
            request_key,
            proposed_task_id,
            _IDEMPOTENCY_TTL_SECONDS,
        )

        if not claim.acquired:
            return EnqueueIntentResult(
                task_id=claim.value,
                created=False,
            )  # return task_id if there is already same task in the backend stream. 
        # The task will expire in a time set by the backend. 

        try:
            await self._conversation_store.touch_session(
                session_id=intent.shopping_session_id,
                buyer_id=intent.buyer_id,
                locale=intent.locale,
                currency=intent.currency,
            )
        except Exception as error:
            await self._release_claim(request_key, claim.value)
            # task not finished, release idempotency.

            if isinstance(error, ValueError):
                raise SessionOwnershipError(str(error)) from error

            raise

        task = IntentTask(
            task_id=claim.value,
            shopping_session_id=intent.shopping_session_id,
            buyer_id=intent.buyer_id,
            locale=intent.locale,
            currency=intent.currency,
            raw_query=intent.raw_query,
            priority=await self._priority(intent.shopping_session_id),
        )

        try:
            await self._task_queue.enqueue(task)
        except Exception:
            await self._release_claim(request_key, claim.value)
            raise

        self._event_publisher.publish(
            intent.shopping_session_id,
            TradeEventType.TASK_QUEUED,
            {"task_id": task.task_id},
        )
        return EnqueueIntentResult(task_id=task.task_id, created=True)

    async def _release_claim(self, key: str, value: str) -> None:
        try:
            await self._idempotency.release(key, value)
        except Exception as release_error:
            logger.warning(
                "Failed to release idempotency reservation: %s",
                release_error,
            )

    async def _priority(self, session_id: str) -> int:
        if not self._priority_enabled:
            return 0

        try:
            turns = await self._conversation_store.list_turns(
                session_id,
                limit=self._large_request_turns,
            )
        except Exception as error:
            logger.warning(
                "Conversation size lookup failed; using normal queue: %s",
                error,
            )
            return 0

        return int(len(turns) >= self._large_request_turns)

    @staticmethod
    def _request_key(
        intent: SubmitIntentInput,
        idempotency_key: str | None,
    ) -> str:
        stable_input = idempotency_key or json.dumps(
            {
                "session": intent.shopping_session_id,
                "buyer": intent.buyer_id,
                "locale": intent.locale,
                "currency": intent.currency,
                "query": intent.raw_query,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(
            f"{intent.buyer_id}:{stable_input}".encode("utf-8")
        ).hexdigest()
        return f"globex:idem:{digest}"


class TaskNotFoundError(LookupError):
    """Raised when a task status has expired or never existed."""


class TaskOwnershipError(PermissionError):
    """Raised when a buyer asks for another buyer's task."""


class GetTaskStatusUseCase:
    def __init__(self, task_queue: TaskQueue) -> None:
        self._task_queue = task_queue

    async def execute(self, task_id: str, buyer_id: str) -> TaskStatus:
        status = await self._task_queue.get_status(task_id)

        if status is None:
            raise TaskNotFoundError(f"Task {task_id} was not found")

        if status.buyer_id != buyer_id:
            raise TaskOwnershipError(
                f"Task {task_id} belongs to another buyer"
            )

        return status
