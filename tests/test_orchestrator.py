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
from tests.fakes import ScriptedChatModel


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
    sessions = SessionRegistry(factory)
    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
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
    
