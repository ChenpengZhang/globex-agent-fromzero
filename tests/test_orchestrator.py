import pytest

from agentscope.message import TextBlock
from agentscope.model import ChatResponse

from app.application.agents.main_agent import (
    MainAgentFactory,
)
from app.application.agents.orchestrator import (
    MainAgentOrchestrator,
    SubmitIntentInput,
)
from app.application.agents.session_registry import SessionRegistry
from app.application.events import TradeEventType
from app.infrastructure.eventbus import InMemoryTradeEventBus
from tests.fakes import (
    InMemoryConversationStore,
    InMemorySessionStore,
    ScriptedChatModel,
)


def test_submit_intent_input_normalizes_values() -> None:
    intent = SubmitIntentInput(
        shopping_session_id=" session-001 ",
        buyer_id=" buyer-001 ",
        locale="",
        currency="cny",
        raw_query=" 推荐旅行装备 ",
    )

    assert intent.shopping_session_id == "session-001"
    assert intent.buyer_id == "buyer-001"
    assert intent.locale == "zh-CN"
    assert intent.currency == "CNY"
    assert intent.raw_query == "推荐旅行装备"


@pytest.mark.parametrize(
    "values",
    [
        {
            "shopping_session_id": "",
            "buyer_id": "buyer-001",
            "locale": "zh-CN",
            "currency": "CNY",
            "raw_query": "推荐旅行装备",
        },
        {
            "shopping_session_id": "session-001",
            "buyer_id": "",
            "locale": "zh-CN",
            "currency": "CNY",
            "raw_query": "推荐旅行装备",
        },
        {
            "shopping_session_id": "session-001",
            "buyer_id": "buyer-001",
            "locale": "zh-CN",
            "currency": "CNY",
            "raw_query": "",
        },
        {
            "shopping_session_id": "session-001",
            "buyer_id": "buyer-001",
            "locale": "zh-CN",
            "currency": "CN",
            "raw_query": "推荐旅行装备",
        },
    ],
)
def test_submit_intent_input_rejects_invalid_values(
    values: dict,
) -> None:
    with pytest.raises(ValueError):
        SubmitIntentInput(**values)


@pytest.mark.asyncio
async def test_orchestrator_builds_agent_message() -> None:
    model = ScriptedChatModel(
        responses=[
            ChatResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="你好，我是 Globex。",
                    ),
                ],
                is_last=True,
            ),
        ],
    )

    factory = MainAgentFactory(
        model=model,
        tools=[],
    )
    session_store = InMemorySessionStore()
    sessions = SessionRegistry(factory, session_store)
    event_bus = InMemoryTradeEventBus()
    event_queue = event_bus.subscribe("session-001")
    conversation_store = InMemoryConversationStore()
    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
        event_bus=event_bus,
        conversation_store=conversation_store,
    )

    result = await orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-001",
            buyer_id="buyer-001",
            locale="zh-CN",
            currency="cny",
            raw_query="你好",
        ),
    )

    assert result.shopping_session_id == "session-001"
    assert result.final_text == "你好，我是 Globex。"

    token_event = event_queue.get_nowait()
    final_event = event_queue.get_nowait()
    assert token_event.type is TradeEventType.TOKEN_DELTA
    assert token_event.payload == {
        "agent_name": "commerce_concierge",
        "token": "你好，我是 Globex。",
    }
    assert final_event.type is TradeEventType.FINAL_RESULT
    assert final_event.payload == {"text": "你好，我是 Globex。"}
    assert event_queue.empty()
    assert "session-001" in session_store.snapshots
    assert [turn.role for turn in conversation_store.turns] == [
        "buyer",
        "agent",
    ]
    assert [turn.content for turn in conversation_store.turns] == [
        "你好",
        "你好，我是 Globex。",
    ]
    assert [event.type for event in conversation_store.events] == [
        "final.result",
    ]

    assert len(model.calls) == 1

    sent_messages = model.calls[0]["messages"]

    buyer_messages = [
        message
        for message in sent_messages
        if (
            message.role == "user"
            and message.name == "buyer-001"
        )
    ]

    assert len(buyer_messages) == 1

    content = (
        buyer_messages[0].get_text_content()
        or ""
    )

    assert "<shopping-context>" in content
    assert "locale: zh-CN" in content
    assert "currency: CNY" in content
    assert "你好" in content


@pytest.mark.asyncio
async def test_orchestrator_persists_state_when_agent_fails() -> None:
    model = ScriptedChatModel(responses=[])
    factory = MainAgentFactory(model=model, tools=[])
    session_store = InMemorySessionStore()
    sessions = SessionRegistry(factory, session_store)
    event_bus = InMemoryTradeEventBus()
    event_queue = event_bus.subscribe("session-error")
    conversation_store = InMemoryConversationStore()
    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
        event_bus=event_bus,
        conversation_store=conversation_store,
    )

    with pytest.raises(
        AssertionError,
        match="没有更多预设响应",
    ):
        await orchestrator.handle_intent(
            SubmitIntentInput(
                shopping_session_id="session-error",
                buyer_id="buyer-001",
                locale="zh-CN",
                currency="CNY",
                raw_query="触发模型错误",
            ),
        )

    assert "session-error" in session_store.snapshots
    events = []
    while not event_queue.empty():
        events.append(event_queue.get_nowait())
    assert events[-1].type is TradeEventType.ERROR
    assert [turn.role for turn in conversation_store.turns] == [
        "buyer",
    ]
    assert [event.type for event in conversation_store.events] == [
        "error",
    ]
