import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from app.application.events import TradeEvent


logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "globex:events:"


class RedisEventBackplane:
    """Redis Pub/Sub transport for ephemeral cross-process events."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._origin = uuid.uuid4().hex

    async def publish(self, event: TradeEvent) -> None:
        await self._client.publish(
            f"{_CHANNEL_PREFIX}{event.shopping_session_id}",
            json.dumps(
                {
                    "origin": self._origin,
                    "event": event.to_dict(),
                },
                ensure_ascii=False,
            ),
        )

    async def listen(
        self,
        handler: Callable[[TradeEvent], None],
        should_stop: Callable[[], bool],
    ) -> None:
        while not should_stop():
            pubsub = None

            try:
                pubsub = self._client.pubsub()
                await pubsub.psubscribe(f"{_CHANNEL_PREFIX}*")

                while not should_stop():
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )

                    if message is not None:
                        self._forward(message, handler)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "Redis event subscription failed; retrying: %s",
                    error,
                )

                if not should_stop():
                    await asyncio.sleep(1)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception as error:
                        logger.warning(
                            "Redis event subscription close failed: %s",
                            error,
                        )

    def _forward(
        self,
        message: dict[str, Any],
        handler: Callable[[TradeEvent], None],
    ) -> None:
        try:
            raw_data = message["data"]

            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")

            envelope = json.loads(raw_data)

            if envelope.get("origin") == self._origin:
                return

            raw_event = envelope["event"]

            if not isinstance(raw_event, dict):
                raise ValueError("Event payload must be an object")

            handler(TradeEvent.from_dict(raw_event))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            logger.warning("Discarding invalid Redis event: %s", error)
