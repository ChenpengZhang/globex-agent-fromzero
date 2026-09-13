import asyncio

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from collections.abc import Callable
from typing import Any, Protocol


class TradeEventType(StrEnum):
    TASK_QUEUED = "task.queued"
    TASK_STARTED = "task.started"
    AGENT_DISPATCH = "agent.dispatch"
    TOOL_INVOKE = "tool.invoke"
    TOOL_RESULT = "tool.result"
    CACHE_HIT = "cache.hit"
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

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TradeEvent":
        occurred_at = datetime.fromisoformat(str(raw["occurred_at"]))

        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        payload = raw["payload"]

        if not isinstance(payload, dict):
            raise ValueError("TradeEvent.payload must be an object")

        return cls(
            shopping_session_id=str(raw["shopping_session_id"]),
            type=TradeEventType(raw["type"]),
            payload=payload,
            occurred_at=occurred_at,
        )


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


RemoteEventHandler = Callable[[TradeEvent], None]


class EventBackplane(Protocol):
    """Move events between independently running processes."""

    async def publish(self, event: TradeEvent) -> None:
        ...

    async def listen(
        self,
        handler: RemoteEventHandler,
        should_stop: Callable[[], bool],
    ) -> None:
        ...
