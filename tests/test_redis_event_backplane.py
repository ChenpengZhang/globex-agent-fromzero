import json

import pytest

from app.application.events import TradeEvent, TradeEventType
from app.infrastructure.queue.redis_event_backplane import RedisEventBackplane


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))


@pytest.mark.asyncio
async def test_publish_uses_a_session_scoped_channel() -> None:
    redis = FakeRedis()
    backplane = RedisEventBackplane(redis)
    event = TradeEvent(
        shopping_session_id="session-001",
        type=TradeEventType.FINAL_RESULT,
        payload={"text": "完成"},
    )

    await backplane.publish(event)

    channel, raw = redis.published[0]
    envelope = json.loads(raw)
    assert channel == "globex:events:session-001"
    assert envelope["event"] == event.to_dict()


def test_forward_delivers_remote_event_and_ignores_own_event() -> None:
    backplane = RedisEventBackplane(FakeRedis())
    received: list[TradeEvent] = []
    event = TradeEvent(
        shopping_session_id="session-001",
        type=TradeEventType.TOKEN_DELTA,
        payload={"token": "A"},
    )

    backplane._forward(
        {
            "data": json.dumps(
                {"origin": "another-process", "event": event.to_dict()}
            )
        },
        received.append,
    )
    backplane._forward(
        {
            "data": json.dumps(
                {"origin": backplane._origin, "event": event.to_dict()}
            )
        },
        received.append,
    )

    assert received == [event]


def test_forward_discards_invalid_messages() -> None:
    backplane = RedisEventBackplane(FakeRedis())
    received: list[TradeEvent] = []

    backplane._forward({"data": "not-json"}, received.append)

    assert received == []
