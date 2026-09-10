from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


VALID_ROLES = ("buyer", "agent")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ConversationTurn:
    """A human readable chat history"""

    session_id: str
    buyer_id: str
    role: str
    content: str
    model: str = ""
    latency_ms: int = 0
    created_at: str = field(
        default_factory=_now_iso,
    )

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError(
                "ConversationTurn.session_id 不能为空",
            )

        if not self.buyer_id.strip():
            raise ValueError(
                "ConversationTurn.buyer_id 不能为空",
            )

        if self.role not in VALID_ROLES:
            raise ValueError(
                "ConversationTurn.role "
                f"必须是 {VALID_ROLES}",
            )

        if self.latency_ms < 0:
            raise ValueError(
                "ConversationTurn.latency_ms 不能为负数",
            )


@dataclass(frozen=True)
class ConversationEventRecord:
    """An agent execution event that needs to be stored."""

    session_id: str
    type: str
    payload: dict[str, Any]
    occurred_at: str = field(
        default_factory=_now_iso,
    )

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError(
                "ConversationEventRecord.session_id "
                "不能为空",
            )

        if not self.type.strip():
            raise ValueError(
                "ConversationEventRecord.type 不能为空",
            )


class ConversationStore(ABC):
    @abstractmethod
    async def touch_session(
        self,
        session_id: str,
        buyer_id: str,
        locale: str,
        currency: str,
    ) -> None:
        """Create conversation metadata, when exists refresh it to active."""

    @abstractmethod
    async def append_turn(
        self,
        turn: ConversationTurn,
    ) -> None:
        """Append a buyer or agent round of talk"""

    @abstractmethod
    async def append_events(
        self,
        events: list[ConversationEventRecord],
    ) -> None:
        """Append multiple events at once"""

    @abstractmethod
    async def list_turns(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[ConversationTurn]:
        """Return conversation history based on the writing order"""

    @abstractmethod
    async def find_session(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """query the conversation matadata, return None if non-existent"""
