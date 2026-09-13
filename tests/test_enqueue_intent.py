import pytest

from app.application.agents.orchestrator import SubmitIntentInput
from app.application.agents.session_registry import SessionOwnershipError
from app.application.events import TradeEventType
from app.application.idempotency import IdempotencyClaim
from app.application.usecases.enqueue_intent import (
    EnqueueIntentUseCase,
    GetTaskStatusUseCase,
    TaskNotFoundError,
    TaskOwnershipError,
)
from app.domain.queue.ports.task_queue import IntentTask, TaskState, TaskStatus
from app.domain.session.ports.conversation_store import ConversationTurn
from app.infrastructure.eventbus import InMemoryTradeEventBus
from tests.fakes import InMemoryConversationStore


class MemoryIdempotency:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.released: list[tuple[str, str]] = []

    async def claim(self, key, proposed_value, ttl_seconds):
        assert ttl_seconds == 300

        if key in self.values:
            return IdempotencyClaim(self.values[key], False)

        self.values[key] = proposed_value
        return IdempotencyClaim(proposed_value, True)

    async def release(self, key, expected_value):
        self.released.append((key, expected_value))

        if self.values.get(key) != expected_value:
            return False

        del self.values[key]
        return True


class MemoryTaskQueue:
    def __init__(self, error: Exception | None = None) -> None:
        self.tasks: list[IntentTask] = []
        self.statuses: dict[str, TaskStatus] = {}
        self.error = error

    async def ensure_ready(self) -> None:
        return None

    async def enqueue(self, task: IntentTask) -> None:
        if self.error is not None:
            raise self.error

        self.tasks.append(task)
        self.statuses[task.task_id] = TaskStatus(
            task_id=task.task_id,
            shopping_session_id=task.shopping_session_id,
            buyer_id=task.buyer_id,
            state=TaskState.QUEUED,
        )

    async def get_status(self, task_id: str):
        return self.statuses.get(task_id)

    async def set_status(self, status: TaskStatus) -> None:
        self.statuses[status.task_id] = status

    async def depth(self) -> int:
        return sum(
            status.state is TaskState.QUEUED
            for status in self.statuses.values()
        )


def intent(**overrides) -> SubmitIntentInput:
    values = {
        "shopping_session_id": "session-001",
        "buyer_id": "buyer-001",
        "locale": "zh-CN",
        "currency": "CNY",
        "raw_query": "推荐一个轻量背包",
    }
    values.update(overrides)
    return SubmitIntentInput(**values)


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_and_publishes_only_once() -> None:
    queue = MemoryTaskQueue()
    idempotency = MemoryIdempotency()
    conversations = InMemoryConversationStore()
    events = InMemoryTradeEventBus()
    subscription = events.subscribe("session-001")
    use_case = EnqueueIntentUseCase(
        queue, idempotency, conversations, events
    )

    first = await use_case.execute(intent(), "browser-request-1")
    second = await use_case.execute(intent(), "browser-request-1")

    assert first.created is True
    assert second.created is False
    assert second.task_id == first.task_id
    assert len(queue.tasks) == 1
    event = subscription.get_nowait()
    assert event.type is TradeEventType.TASK_QUEUED
    assert event.payload == {"task_id": first.task_id}
    assert subscription.empty()


@pytest.mark.asyncio
async def test_enqueue_rejects_session_owned_by_another_buyer() -> None:
    conversations = InMemoryConversationStore()
    use_case = EnqueueIntentUseCase(
        MemoryTaskQueue(),
        MemoryIdempotency(),
        conversations,
        InMemoryTradeEventBus(),
    )
    await use_case.execute(intent(), "request-1")

    with pytest.raises(SessionOwnershipError, match="another buyer"):
        await use_case.execute(
            intent(buyer_id="buyer-002"),
            "request-2",
        )


@pytest.mark.asyncio
async def test_long_conversation_uses_large_task_priority() -> None:
    conversations = InMemoryConversationStore()

    for index in range(3):
        await conversations.append_turn(
            ConversationTurn(
                session_id="session-001",
                buyer_id="buyer-001",
                role="buyer",
                content=f"turn {index}",
            )
        )

    queue = MemoryTaskQueue()
    use_case = EnqueueIntentUseCase(
        queue,
        MemoryIdempotency(),
        conversations,
        InMemoryTradeEventBus(),
        large_request_turns=3,
    )

    await use_case.execute(intent(), "request-1")

    assert queue.tasks[0].priority == 1


@pytest.mark.asyncio
async def test_failed_enqueue_releases_idempotency_reservation() -> None:
    idempotency = MemoryIdempotency()
    use_case = EnqueueIntentUseCase(
        MemoryTaskQueue(ConnectionError("redis unavailable")),
        idempotency,
        InMemoryConversationStore(),
        InMemoryTradeEventBus(),
    )

    with pytest.raises(ConnectionError, match="redis unavailable"):
        await use_case.execute(intent(), "request-1")

    assert len(idempotency.released) == 1
    assert idempotency.values == {}


@pytest.mark.asyncio
async def test_task_status_enforces_existence_and_ownership() -> None:
    queue = MemoryTaskQueue()
    status = TaskStatus(
        task_id="task-001",
        shopping_session_id="session-001",
        buyer_id="buyer-001",
        state=TaskState.DONE,
        final_text="完成",
    )
    queue.statuses[status.task_id] = status
    use_case = GetTaskStatusUseCase(queue)

    assert await use_case.execute("task-001", "buyer-001") == status

    with pytest.raises(TaskOwnershipError):
        await use_case.execute("task-001", "buyer-002")

    with pytest.raises(TaskNotFoundError):
        await use_case.execute("missing", "buyer-001")
