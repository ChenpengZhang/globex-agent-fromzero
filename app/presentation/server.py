import uuid

from fastapi import FastAPI, HTTPException

from app.application.agents.orchestrator import (
    SubmitIntentInput,
)
from app.application.agents.session_registry import (
    SessionOwnershipError,
)
from app.composition import Container, build_container
from app.presentation.dto import (
    SubmitIntentRequest,
    SubmitIntentResponse,
)


def build_app(
    container: Container | None = None,
) -> FastAPI:
    runtime_container = container or build_container()
    # Leave space for fake offline container

    api = FastAPI(
        title="Globex Cross-Border Commerce Agent",
        version="0.1.0",
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

    return api
