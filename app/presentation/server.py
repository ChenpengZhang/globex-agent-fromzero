import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from typing import Annotated

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
)

from app.application.agents.orchestrator import (
    SubmitIntentInput,
)
from app.application.agents.session_registry import (
    SessionOwnershipError,
)
from app.application.usecases.get_conversation_history import (
    ConversationNotFoundError,
    ConversationOwnershipError,
    GetConversationHistoryInput,
)
from app.application.usecases.enqueue_intent import (
    TaskNotFoundError,
    TaskOwnershipError,
)
from app.composition import Container, build_container
from app.presentation.dto import (
    ConversationHistoryResponse,
    ConversationTurnResponse,
    AsyncSubmitIntentResponse,
    SubmitIntentRequest,
    SubmitIntentResponse,
    TaskStatusResponse,
)
from app.presentation.connection import (
    ConnectionManager,
)


logger = logging.getLogger(__name__)


def build_app(
    container: Container | None = None,
) -> FastAPI:
    runtime_container = container or build_container()
    # Leave space for fake offline container

    connection_manager = ConnectionManager(
        runtime_container.event_bus,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await runtime_container.startup()
        relay_stop = asyncio.Event()
        relay_task: asyncio.Task[None] | None = None

        if runtime_container.event_backplane is not None:
            relay_task = asyncio.create_task(
                runtime_container.event_backplane.listen(
                    runtime_container.event_bus.deliver_remote,
                    relay_stop.is_set,
                )
            )

        try:
            yield
        finally:
            relay_stop.set()

            if relay_task is not None:
                try:
                    await asyncio.wait_for(relay_task, timeout=2)
                except TimeoutError:
                    relay_task.cancel()
                    await asyncio.gather(
                        relay_task,
                        return_exceptions=True,
                    )

            await runtime_container.shutdown()

    api = FastAPI(
        title="Globex Cross-Border Commerce Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    @api.get("/health")
    async def health() -> dict:
        redis_state = "disabled"
        queue_depth = 0

        if runtime_container.cache.enabled:
            redis_state = (
                "ok"
                if await runtime_container.cache.ping()
                else "error"
            )

        if runtime_container.task_queue is not None:
            queue_depth = await runtime_container.task_queue.depth()

        return {
            "status": "ok",
            "redis": redis_state,
            "semantic_cache": (
                runtime_container.semantic_cache.enabled
            ),
            "queue": (
                "enabled"
                if runtime_container.task_queue is not None
                else "disabled"
            ),
            "queue_depth": queue_depth,
        }

    @api.post(
        "/commerce/intents",
        response_model=SubmitIntentResponse,
    )
    async def submit_intent(
        body: SubmitIntentRequest,
    ) -> SubmitIntentResponse:
        session_id = (
            body.shopping_session_id
            or f"session-{uuid.uuid4().hex[:8]}"
        )

        intent = SubmitIntentInput(
            shopping_session_id=session_id,
            buyer_id=body.buyer_id,
            locale=body.locale,
            currency=body.currency,
            raw_query=body.raw_query,
        )

        try:
            result = (
                await runtime_container.orchestrator.handle_intent(
                    intent,
                )
            )
        except SessionOwnershipError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error

        return SubmitIntentResponse(
            shopping_session_id=(
                result.shopping_session_id
            ),
            final_text=result.final_text,
        )

    @api.post(
        "/commerce/intents/async",
        response_model=AsyncSubmitIntentResponse,
        status_code=202,
    )
    async def submit_intent_async(
        body: SubmitIntentRequest,
    ) -> AsyncSubmitIntentResponse:
        enqueue_intent = runtime_container.enqueue_intent

        if enqueue_intent is None:
            raise HTTPException(
                status_code=503,
                detail="Asynchronous task queue is disabled",
            )

        session_id = (
            body.shopping_session_id
            or f"session-{uuid.uuid4().hex[:8]}"
        )
        intent = SubmitIntentInput(
            shopping_session_id=session_id,
            buyer_id=body.buyer_id,
            locale=body.locale,
            currency=body.currency,
            raw_query=body.raw_query,
        )

        try:
            result = await enqueue_intent.execute(
                intent,
                idempotency_key=body.idempotency_key,
            )
        except SessionOwnershipError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error
        except Exception as error:
            logger.warning("Task submission failed: %s", error)
            raise HTTPException(
                status_code=503,
                detail="Task queue is temporarily unavailable",
            ) from error

        state = "queued"
        response_session_id = session_id

        if not result.created and runtime_container.task_queue is not None:
            status = await runtime_container.task_queue.get_status(
                result.task_id
            )

            if status is not None:
                state = status.state
                response_session_id = status.shopping_session_id

        return AsyncSubmitIntentResponse(
            shopping_session_id=response_session_id,
            task_id=result.task_id,
            state=state,
        )

    @api.get(
        "/commerce/tasks/{task_id}",
        response_model=TaskStatusResponse,
    )
    async def get_task_status(
        task_id: str,
        buyer_id: Annotated[str, Query(min_length=1)],
    ) -> TaskStatusResponse:
        use_case = runtime_container.get_task_status

        if use_case is None:
            raise HTTPException(
                status_code=503,
                detail="Asynchronous task queue is disabled",
            )

        try:
            status = await use_case.execute(task_id, buyer_id)
        except TaskNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error
        except TaskOwnershipError as error:
            raise HTTPException(
                status_code=403,
                detail=str(error),
            ) from error

        return TaskStatusResponse(**status.to_dict())

    @api.get(
        "/commerce/sessions/{session_id}/history",
        response_model=ConversationHistoryResponse,
    )
    async def get_conversation_history(
        session_id: str,
        buyer_id: Annotated[
            str,
            Query(min_length=1),
        ],
        limit: Annotated[
            int,
            Query(ge=1, le=100),
        ] = 50,
    ) -> ConversationHistoryResponse:
        try:
            result = (
                await runtime_container
                .get_conversation_history
                .execute(
                    GetConversationHistoryInput(
                        session_id=session_id,
                        buyer_id=buyer_id,
                        limit=limit,
                    )
                )
            )

        except ConversationNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error

        except ConversationOwnershipError as error:
            raise HTTPException(
                status_code=403,
                detail=str(error),
            ) from error

        return ConversationHistoryResponse(
            session_id=result.session_id,
            turns=[
                ConversationTurnResponse(
                    role=turn.role,
                    content=turn.content,
                    model=turn.model,
                    latency_ms=turn.latency_ms,
                    created_at=turn.created_at,
                )
                for turn in result.turns
            ],
        )

    @api.websocket("/commerce/events")
    async def commerce_events(
        websocket: WebSocket,
    ) -> None:
        await connection_manager.serve(websocket)

    return api
