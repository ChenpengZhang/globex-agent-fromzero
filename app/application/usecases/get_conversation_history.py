from dataclasses import dataclass

from app.application.dto.conversation import (
    ConversationHistoryOutput,
    ConversationTurnOutput,
)
from app.domain.session.ports.conversation_store import (
    ConversationStore,
)


class ConversationNotFoundError(LookupError):
    """Raised when a conversation session does not exist."""


class ConversationOwnershipError(PermissionError):
    """Raised when a conversation belongs to another buyer."""


@dataclass(frozen=True)
class GetConversationHistoryInput:
    session_id: str
    buyer_id: str
    limit: int = 50

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError(
                "session_id cannot be empty",
            )

        if not self.buyer_id.strip():
            raise ValueError(
                "buyer_id cannot be empty",
            )

        if not 1 <= self.limit <= 100:
            raise ValueError(
                "limit must be between 1 and 100",
            )

        object.__setattr__(
            self,
            "session_id",
            self.session_id.strip(),
        )
        object.__setattr__(
            self,
            "buyer_id",
            self.buyer_id.strip(),
        )


class GetConversationHistoryUseCase:
    def __init__(
        self,
        conversation_store: ConversationStore,
    ) -> None:
        self._conversation_store = conversation_store

    async def execute(
        self,
        request: GetConversationHistoryInput,
    ) -> ConversationHistoryOutput:
        session = (
            await self._conversation_store.find_session(
                request.session_id,
            )
        )

        if session is None:
            raise ConversationNotFoundError(
                "Conversation session was not found",
            )

        if session.get("buyer_id") != request.buyer_id:
            raise ConversationOwnershipError(
                "Conversation session belongs "
                "to another buyer",
            )

        turns = await self._conversation_store.list_turns(
            session_id=request.session_id,
            limit=request.limit,
        )

        return ConversationHistoryOutput(
            session_id=request.session_id,
            turns=[
                ConversationTurnOutput(
                    role=turn.role,
                    content=turn.content,
                    model=turn.model,
                    latency_ms=turn.latency_ms,
                    created_at=turn.created_at,
                )
                for turn in turns
            ],
        )
    