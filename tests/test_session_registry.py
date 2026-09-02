import asyncio

import pytest

from agentscope.message import TextBlock
from agentscope.model import ChatResponse

from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import (
    MainAgentOrchestrator,
    SubmitIntentInput,
)
from app.application.agents.session_registry import (
    SessionOwnershipError,
    SessionRegistry,
)
from tests.fakes import ScriptedChatModel


def build_registry(
    responses: list[ChatResponse] | None = None,
) -> tuple[SessionRegistry, ScriptedChatModel]:
    model = ScriptedChatModel(
        responses=responses or [],
    )
    factory = MainAgentFactory(
        model=model,
        tools=[],
    )
    return SessionRegistry(factory), model


@pytest.mark.asyncio
async def test_same_session_and_buyer_reuses_agent() -> None:
    sessions, _ = build_registry()

    first = await sessions.get_or_create(
        "session-001",
        "buyer-001",
    )
    second = await sessions.get_or_create(
        "session-001",
        "buyer-001",
    )

    assert first is second
    assert first.agent is second.agent
    assert len(sessions) == 1


@pytest.mark.asyncio
async def test_different_sessions_receive_different_agents() -> None:
    sessions, _ = build_registry()

    first = await sessions.get_or_create(
        "session-001",
        "buyer-001",
    )
    second = await sessions.get_or_create(
        "session-002",
        "buyer-001",
    )

    assert first.agent is not second.agent
    assert first.agent.state is not second.agent.state
    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_session_cannot_be_reused_by_other_buyer() -> None:
    sessions, _ = build_registry()

    await sessions.get_or_create(
        "session-001",
        "buyer-001",
    )

    with pytest.raises(SessionOwnershipError):
        await sessions.get_or_create(
            "session-001",
            "buyer-002",
        )


@pytest.mark.asyncio
async def test_concurrent_creation_returns_one_session_entry() -> None:
    sessions, _ = build_registry()

    entries = await asyncio.gather(
        *[
            sessions.get_or_create(
                "session-concurrent",
                "buyer-001",
            )
            for _ in range(20)
        ],
    )

    assert len({id(entry) for entry in entries}) == 1
    assert len({id(entry.agent) for entry in entries}) == 1
    assert len(sessions) == 1


@pytest.mark.asyncio
async def test_orchestrator_isolates_context_between_sessions() -> None:
    responses = [
        ChatResponse(
            content=[TextBlock(type="text", text="A 的回复")],
            is_last=True,
        ),
        ChatResponse(
            content=[TextBlock(type="text", text="B 的回复")],
            is_last=True,
        ),
    ]
    sessions, _ = build_registry(responses)
    orchestrator = MainAgentOrchestrator(sessions)

    await orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-A",
            buyer_id="buyer-A",
            locale="zh-CN",
            currency="CNY",
            raw_query="A 的私有问题",
        ),
    )
    await orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-B",
            buyer_id="buyer-B",
            locale="zh-CN",
            currency="CNY",
            raw_query="B 的私有问题",
        ),
    )

    session_a = await sessions.get_or_create(
        "session-A",
        "buyer-A",
    )
    session_b = await sessions.get_or_create(
        "session-B",
        "buyer-B",
    )

    context_a = "\n".join(
        message.get_text_content() or ""
        for message in session_a.agent.state.context
    )
    context_b = "\n".join(
        message.get_text_content() or ""
        for message in session_b.agent.state.context
    )

    assert "A 的私有问题" in context_a
    assert "B 的私有问题" not in context_a
    assert "B 的私有问题" in context_b
    assert "A 的私有问题" not in context_b


@pytest.mark.asyncio
async def test_same_session_retains_multiple_turns() -> None:
    responses = [
        ChatResponse(
            content=[TextBlock(type="text", text="第一轮回复")],
            is_last=True,
        ),
        ChatResponse(
            content=[TextBlock(type="text", text="第二轮回复")],
            is_last=True,
        ),
    ]
    sessions, _ = build_registry(responses)
    orchestrator = MainAgentOrchestrator(sessions)

    for query in ("第一轮问题", "第二轮问题"):
        await orchestrator.handle_intent(
            SubmitIntentInput(
                shopping_session_id="session-multi-turn",
                buyer_id="buyer-001",
                locale="zh-CN",
                currency="CNY",
                raw_query=query,
            ),
        )

    session = await sessions.get_or_create(
        "session-multi-turn",
        "buyer-001",
    )
    context = "\n".join(
        message.get_text_content() or ""
        for message in session.agent.state.context
    )

    assert "第一轮问题" in context
    assert "第一轮回复" in context
    assert "第二轮问题" in context
    assert "第二轮回复" in context
    assert len(sessions) == 1
