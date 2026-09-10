import asyncio
from collections import defaultdict
from typing import Any

from app.application.events import (
    TradeEvent,
    TradeEventType,
)


class InMemoryTradeEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[
            str,
            set[asyncio.Queue[TradeEvent]],
        ] = defaultdict(set)

    def subscribe(
        self,
        shopping_session_id: str,
    ) -> asyncio.Queue[TradeEvent]:
        queue: asyncio.Queue[TradeEvent] = asyncio.Queue()
        self._subscribers[shopping_session_id].add(queue)
        return queue

    def unsubscribe(
        self,
        shopping_session_id: str,
        queue: asyncio.Queue[TradeEvent],
    ) -> None:
        subscribers = self._subscribers.get(
            shopping_session_id,
        )

        if subscribers is None:
            return

        subscribers.discard(queue)

        if not subscribers:
            self._subscribers.pop(
                shopping_session_id,
                None,
            )

    def publish(
        self,
        shopping_session_id: str,
        event_type: TradeEventType,
        payload: dict[str, Any],
    ) -> TradeEvent:
        event = TradeEvent(
            shopping_session_id=shopping_session_id,
            type=event_type,
            payload=payload,
        )

        for queue in tuple(
            self._subscribers.get(
                shopping_session_id,
                (),
            )
        ):
            queue.put_nowait(event)

        return event
    