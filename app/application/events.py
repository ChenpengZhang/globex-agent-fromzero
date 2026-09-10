import asyncio

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol


class TradeEventType(StrEnum):
    AGENT_DISPATCH = "agent.dispatch"
    TOOL_INVOKE = "tool.invoke"
    TOOL_RESULT = "tool.result"
    TOKEN_DELTA = "token.delta"
    FINAL_RESULT = "final.result"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TradeEvent:
    shopping_session_id: str
    type: TradeEventType
    payload: dict[str, Any]
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "shopping_session_id": self.shopping_session_id,
            "type": self.type.value,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
        }


class EventPublisher(Protocol):
    def publish(
        self,
        shopping_session_id: str,
        event_type: TradeEventType,
        payload: dict[str, Any],
    ) -> TradeEvent:
        ...

class EventBus(EventPublisher, Protocol):
    """Publish and subscribe to session-scoped trade events."""

    def subscribe(
        self,
        shopping_session_id: str,
    ) -> asyncio.Queue[TradeEvent]:
        ...

    def unsubscribe(
        self,
        shopping_session_id: str,
        queue: asyncio.Queue[TradeEvent],
    ) -> None:
        ...
