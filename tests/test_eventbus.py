import asyncio
from datetime import timezone

import pytest

from app.application.events import TradeEvent, TradeEventType
from app.infrastructure.eventbus import InMemoryTradeEventBus


def test_publish_serializes_a_typed_event() -> None:
    bus = InMemoryTradeEventBus()

    event = bus.publish(
        "session-001",
        TradeEventType.TOOL_INVOKE,
        {"tool_name": "search_products"},
    )

    assert event.shopping_session_id == "session-001"
    assert event.type is TradeEventType.TOOL_INVOKE
    assert event.occurred_at.tzinfo is timezone.utc
    assert event.to_dict() == {
        "shopping_session_id": "session-001",
        "type": "tool.invoke",
        "payload": {"tool_name": "search_products"},
        "occurred_at": event.occurred_at.isoformat(),
    }


@pytest.mark.asyncio
async def test_publish_delivers_only_to_the_matching_session() -> None:
    bus = InMemoryTradeEventBus()
    first_queue = bus.subscribe("session-001")
    second_queue = bus.subscribe("session-002")

    published = bus.publish(
        "session-001",
        TradeEventType.TOKEN_DELTA,
        {"token": "hello"},
    )

    assert await asyncio.wait_for(first_queue.get(), timeout=0.1) == published
    assert second_queue.empty()


@pytest.mark.asyncio
async def test_each_subscriber_receives_the_same_event() -> None:
    bus = InMemoryTradeEventBus()
    browser_a = bus.subscribe("session-001")
    browser_b = bus.subscribe("session-001")

    published = bus.publish(
        "session-001",
        TradeEventType.FINAL_RESULT,
        {"text": "done"},
    )

    assert await asyncio.wait_for(browser_a.get(), timeout=0.1) == published
    assert await asyncio.wait_for(browser_b.get(), timeout=0.1) == published


def test_unsubscribe_stops_delivery_and_removes_empty_session() -> None:
    bus = InMemoryTradeEventBus()
    queue = bus.subscribe("session-001")

    bus.unsubscribe("session-001", queue)
    bus.publish(
        "session-001",
        TradeEventType.ERROR,
        {"message": "ignored"},
    )

    assert queue.empty()
    assert "session-001" not in bus._subscribers


@pytest.mark.asyncio
async def test_publish_forwards_to_backplane_without_remote_loop() -> None:
    class RecordingBackplane:
        def __init__(self) -> None:
            self.events: list[TradeEvent] = []

        async def publish(self, event: TradeEvent) -> None:
            self.events.append(event)

    backplane = RecordingBackplane()
    bus = InMemoryTradeEventBus(backplane)
    local = bus.subscribe("session-001")

    published = bus.publish(
        "session-001",
        TradeEventType.TASK_QUEUED,
        {"task_id": "task-001"},
    )
    await bus.drain()
    remote = TradeEvent(
        shopping_session_id="session-001",
        type=TradeEventType.TASK_STARTED,
        payload={"task_id": "task-001"},
    )
    bus.deliver_remote(remote)
    await bus.drain()

    assert backplane.events == [published]
    assert local.get_nowait() == published
    assert local.get_nowait() == remote
