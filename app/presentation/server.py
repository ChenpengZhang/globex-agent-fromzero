import uuid

from typing import Annotated

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
)
from contextlib import asynccontextmanager

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
from app.composition import Container, build_container
from app.presentation.dto import (
    ConversationHistoryResponse,
    ConversationTurnResponse,
    SubmitIntentRequest,
    SubmitIntentResponse,
)
from app.presentation.connection import (
    ConnectionManager,
)


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

        try:
            yield
        finally:
            await runtime_container.shutdown()

    api = FastAPI(
        title="Globex Cross-Border Commerce Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    @api.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
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
