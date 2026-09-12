from contextlib import contextmanager
from typing import Iterator

import pytest
from agentscope.message import ToolResultState
from agentscope.tool import FunctionTool

from app.application.events import TradeEventType
from app.application.tools.preference_tools import (
    build_forget_preference_tool,
    build_remember_preference_tool,
)
from app.domain.buyer.preference import BuyerPreference
from app.infrastructure.context import (
    ShoppingContext,
    ShoppingContextSnapshot,
)
from app.infrastructure.eventbus import InMemoryTradeEventBus
from tests.fakes import InMemoryPreferenceStore


@contextmanager
def shopping_context(
    buyer_id: str,
    session_id: str = "session-001",
) -> Iterator[None]:
    reset_token = ShoppingContext.set(
        ShoppingContextSnapshot(
            shopping_session_id=session_id,
            buyer_id=buyer_id,
            locale="zh-CN",
            currency="CNY",
        )
    )

    try:
        yield
    finally:
        ShoppingContext.reset(reset_token)


def _drain_events(queue) -> list:
    events = []

    while not queue.empty():
        events.append(queue.get_nowait())

    return events


def test_preference_function_tools_do_not_expose_buyer_id() -> None:
    store = InMemoryPreferenceStore()
    bus = InMemoryTradeEventBus()
    remember = FunctionTool(
        build_remember_preference_tool(store, bus),
        is_read_only=False,
    )
    forget = FunctionTool(
        build_forget_preference_tool(store, bus),
        is_read_only=False,
    )

    assert remember.name == "remember_preference_tool"
    assert remember.input_schema["required"] == [
        "kind",
        "statement",
    ]
    assert "buyer_id" not in remember.input_schema["properties"]
    assert forget.name == "forget_preference_tool"
    assert forget.input_schema["required"] == ["statement"]
    assert "buyer_id" not in forget.input_schema["properties"]


@pytest.mark.asyncio
async def test_remember_uses_context_buyer_and_publishes_events() -> None:
    store = InMemoryPreferenceStore()
    bus = InMemoryTradeEventBus()
    queue = bus.subscribe("session-001")
    remember = build_remember_preference_tool(store, bus)

    with shopping_context("buyer-owner"):
        result = await remember(
            kind="dislike",
            statement="  不要塑料材质  ",
        )

    events = _drain_events(queue)

    assert result.state is ToolResultState.SUCCESS
    assert "[dislike] 不要塑料材质" in result.content[0].text
    assert store.preferences[0].buyer_id == "buyer-owner"
    assert store.preferences[0].statement == "不要塑料材质"
    assert [event.type for event in events] == [
        TradeEventType.TOOL_INVOKE,
        TradeEventType.TOOL_RESULT,
    ]
    assert events[1].payload == {
        "tool": "remember_preference_tool",
        "saved": "不要塑料材质",
        "kind": "dislike",
    }


@pytest.mark.asyncio
async def test_remember_rejects_missing_context() -> None:
    store = InMemoryPreferenceStore()
    remember = build_remember_preference_tool(
        store,
        InMemoryTradeEventBus(),
    )

    result = await remember(
        kind="like",
        statement="喜欢小众设计",
    )

    assert result.state is ToolResultState.ERROR
    assert store.preferences == []
    assert "ShoppingContext" in result.content[0].text


@pytest.mark.asyncio
async def test_remember_reports_store_failure_as_tool_error() -> None:
    class FailingStore(InMemoryPreferenceStore):
        async def append(self, preference: BuyerPreference) -> None:
            raise RuntimeError("database unavailable")

    store = FailingStore()
    bus = InMemoryTradeEventBus()
    queue = bus.subscribe("session-001")
    remember = build_remember_preference_tool(store, bus)

    with shopping_context("buyer-001"):
        result = await remember(
            kind="like",
            statement="喜欢小众设计",
        )

    events = _drain_events(queue)

    assert result.state is ToolResultState.ERROR
    assert "database unavailable" in result.content[0].text
    assert events[-1].payload["error"] == "database unavailable"


@pytest.mark.asyncio
async def test_forget_deletes_exact_statement_for_context_buyer() -> None:
    store = InMemoryPreferenceStore()
    bus = InMemoryTradeEventBus()
    forget = build_forget_preference_tool(store, bus)

    for preference in [
        BuyerPreference("buyer-001", "like", "不要塑料"),
        BuyerPreference("buyer-001", "dislike", "不要塑料"),
        BuyerPreference("buyer-001", "dislike", "不要塑料包装"),
        BuyerPreference("buyer-002", "dislike", "不要塑料"),
    ]:
        await store.append(preference)

    with shopping_context("buyer-001"):
        result = await forget("  不要塑料  ")

    assert result.state is ToolResultState.SUCCESS
    assert "已撤回" in result.content[0].text
    assert [
        (item.buyer_id, item.statement)
        for item in store.preferences
    ] == [
        ("buyer-001", "不要塑料包装"),
        ("buyer-002", "不要塑料"),
    ]


@pytest.mark.asyncio
async def test_forget_not_found_lists_remaining_preferences() -> None:
    store = InMemoryPreferenceStore()
    bus = InMemoryTradeEventBus()
    queue = bus.subscribe("session-001")
    forget = build_forget_preference_tool(store, bus)
    await store.append(
        BuyerPreference(
            "buyer-001",
            "dislike",
            "不要塑料包装",
        )
    )

    with shopping_context("buyer-001"):
        result = await forget("不要塑料")

    events = _drain_events(queue)

    assert result.state is ToolResultState.SUCCESS
    assert "没有删除任何内容" in result.content[0].text
    assert "[dislike] 不要塑料包装" in result.content[0].text
    assert events[-1].payload["not_found"] == "不要塑料"
    assert events[-1].payload["remaining"] == 1


@pytest.mark.asyncio
async def test_forget_rejects_empty_statement() -> None:
    bus = InMemoryTradeEventBus()
    queue = bus.subscribe("session-001")
    forget = build_forget_preference_tool(
        InMemoryPreferenceStore(),
        bus,
    )

    with shopping_context("buyer-001"):
        result = await forget("   ")

    events = _drain_events(queue)

    assert result.state is ToolResultState.ERROR
    assert events[-1].payload["error"] == (
        "preference statement cannot be empty"
    )
