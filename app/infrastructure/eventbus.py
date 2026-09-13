import asyncio
import logging
from collections import defaultdict
from typing import Any

from app.application.events import (
    TradeEvent,
    TradeEventType,
    EventBackplane,
)


logger = logging.getLogger(__name__)


class InMemoryTradeEventBus:
    def __init__(
        self,
        backplane: EventBackplane | None = None,
    ) -> None:
        self._backplane = backplane
        self._publishing: set[asyncio.Task[None]] = set()
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

        self.deliver_remote(event)

        if self._backplane is not None:
            try:
                task = asyncio.get_running_loop().create_task(
                    self._publish_remote(event)
                )
            except RuntimeError:
                logger.warning(
                    "Redis event publish skipped outside an event loop"
                )
            else:
                self._publishing.add(task)
                task.add_done_callback(self._publishing.discard)

        return event

    def deliver_remote(self, event: TradeEvent) -> None:
        """Deliver an event locally without republishing it to Redis."""

        for queue in tuple(
            self._subscribers.get(
                event.shopping_session_id,
                (),
            )
        ):
            queue.put_nowait(event)

    async def _publish_remote(self, event: TradeEvent) -> None:
        try:
            assert self._backplane is not None
            await self._backplane.publish(event)
        except Exception as error:
            logger.warning("Redis event publish failed: %s", error)

    async def drain(self) -> None:
        """Wait until already scheduled remote publishes finish."""

        if self._publishing:
            await asyncio.gather(
                *tuple(self._publishing),
                return_exceptions=True,
            )
