import pytest
from agentscope.message import TextBlock
from agentscope.model import ChatResponse

from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import (
    MainAgentOrchestrator,
    SubmitIntentInput,
)
from app.application.agents.session_registry import SessionRegistry
from app.domain.buyer.preference import BuyerPreference
from app.infrastructure.eventbus import InMemoryTradeEventBus
from tests.fakes import (
    InMemoryConversationStore,
    InMemoryPreferenceStore,
    InMemorySessionStore,
    ScriptedChatModel,
)


def response(text: str) -> ChatResponse:
    return ChatResponse(
        content=[
            TextBlock(
                type="text",
                text=text,
            )
        ],
        is_last=True,
    )


def intent(
    session_id: str,
    buyer_id: str,
    query: str = "推荐一个杯子",
) -> SubmitIntentInput:
    return SubmitIntentInput(
        shopping_session_id=session_id,
        buyer_id=buyer_id,
        locale="zh-CN",
        currency="CNY",
        raw_query=query,
    )


def build_orchestrator(
    preference_store,
    responses: list[ChatResponse],
    conversation_store=None,
) -> tuple[MainAgentOrchestrator, ScriptedChatModel, SessionRegistry]:
    model = ScriptedChatModel(responses=responses)
    agent_factory = MainAgentFactory(
        model=model,
        tools=[],
    )
    sessions = SessionRegistry(
        agent_factory,
        InMemorySessionStore(),
    )
    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
        event_bus=InMemoryTradeEventBus(),
        conversation_store=conversation_store,
        preference_store=preference_store,
    )
    return orchestrator, model, sessions


def memory_hints(messages) -> list[str]:
    return [
        message.get_text_content() or ""
        for message in messages
        if message.name == "memory_hint"
    ]


@pytest.mark.asyncio
async def test_same_buyer_receives_memory_in_each_new_session() -> None:
    preferences = InMemoryPreferenceStore()
    await preferences.append(
        BuyerPreference(
            buyer_id="buyer-001",
            kind="dislike",
            statement="不要塑料材质",
        )
    )
    orchestrator, model, _ = build_orchestrator(
        preferences,
        [response("first"), response("second")],
    )

    await orchestrator.handle_intent(
        intent("session-A", "buyer-001")
    )
    await orchestrator.handle_intent(
        intent("session-B", "buyer-001")
    )

    first_hints = memory_hints(model.calls[0]["messages"])
    second_hints = memory_hints(model.calls[1]["messages"])

    assert len(first_hints) == 1
    assert len(second_hints) == 1
    assert "[dislike] 不要塑料材质" in first_hints[0]
    assert "[dislike] 不要塑料材质" in second_hints[0]


@pytest.mark.asyncio
async def test_preferences_do_not_cross_buyer_boundary() -> None:
    preferences = InMemoryPreferenceStore()
    await preferences.append(
        BuyerPreference(
            buyer_id="buyer-A",
            kind="like",
            statement="喜欢小众设计",
        )
    )
    orchestrator, model, _ = build_orchestrator(
        preferences,
        [response("A"), response("B")],
    )

    await orchestrator.handle_intent(
        intent("session-A", "buyer-A")
    )
    await orchestrator.handle_intent(
        intent("session-B", "buyer-B")
    )

    assert "喜欢小众设计" in memory_hints(
        model.calls[0]["messages"]
    )[0]
    assert memory_hints(model.calls[1]["messages"]) == []


@pytest.mark.asyncio
async def test_unchanged_hint_is_not_duplicated_in_agent_state() -> None:
    preferences = InMemoryPreferenceStore()
    await preferences.append(
        BuyerPreference(
            buyer_id="buyer-001",
            kind="like",
            statement="喜欢小众设计",
        )
    )
    orchestrator, _, sessions = build_orchestrator(
        preferences,
        [response("first"), response("second")],
    )

    await orchestrator.handle_intent(
        intent("session-001", "buyer-001", "第一次问题")
    )
    await orchestrator.handle_intent(
        intent("session-001", "buyer-001", "第二次问题")
    )
    session = await sessions.get_or_create(
        "session-001",
        "buyer-001",
    )

    hints = memory_hints(session.agent.state.context)

    assert len(hints) == 1
    assert "喜欢小众设计" in hints[0]


@pytest.mark.asyncio
async def test_readable_history_excludes_internal_memory_hint() -> None:
    preferences = InMemoryPreferenceStore()
    await preferences.append(
        BuyerPreference(
            buyer_id="buyer-001",
            kind="dislike",
            statement="不要塑料材质",
        )
    )
    conversations = InMemoryConversationStore()
    orchestrator, _, _ = build_orchestrator(
        preferences,
        [response("推荐结果")],
        conversation_store=conversations,
    )

    await orchestrator.handle_intent(
        intent(
            "session-001",
            "buyer-001",
            "推荐一个杯子",
        )
    )

    assert [turn.content for turn in conversations.turns] == [
        "推荐一个杯子",
        "推荐结果",
    ]
    assert all(
        "<buyer-preferences>" not in turn.content
        for turn in conversations.turns
    )


@pytest.mark.asyncio
async def test_preference_read_failure_does_not_block_agent() -> None:
    class FailingPreferenceStore(InMemoryPreferenceStore):
        async def list_by_buyer(
            self,
            buyer_id: str,
        ) -> list[BuyerPreference]:
            raise RuntimeError("database unavailable")

    orchestrator, model, _ = build_orchestrator(
        FailingPreferenceStore(),
        [response("正常回复")],
    )

    result = await orchestrator.handle_intent(
        intent("session-001", "buyer-001")
    )

    assert result.final_text == "正常回复"
    assert memory_hints(model.calls[0]["messages"]) == []
