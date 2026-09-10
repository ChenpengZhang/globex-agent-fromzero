import pytest

from app.application.agents.orchestrator import SubmitIntentInput
from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import MainAgentOrchestrator
from app.application.agents.session_registry import SessionRegistry
from app.application.usecases.get_conversation_history import (
    ConversationNotFoundError,
    ConversationOwnershipError,
    GetConversationHistoryInput,
    GetConversationHistoryUseCase,
)
from app.domain.session.ports.conversation_store import ConversationTurn
from app.infrastructure.eventbus import InMemoryTradeEventBus
from tests.fakes import (
    InMemoryConversationStore,
    InMemorySessionStore,
    ScriptedChatModel,
)
from agentscope.message import TextBlock
from agentscope.model import ChatResponse


@pytest.mark.asyncio
async def test_history_returns_mapped_turns_in_store_order() -> None:
    store = InMemoryConversationStore()
    await store.touch_session(
        "session-001",
        "buyer-001",
        "zh-CN",
        "CNY",
    )
    for index in range(3):
        await store.append_turn(
            ConversationTurn(
                session_id="session-001",
                buyer_id="buyer-001",
                role="buyer" if index % 2 == 0 else "agent",
                content=f"turn-{index}",
                model="test-model",
                latency_ms=index,
            )
        )
    usecase = GetConversationHistoryUseCase(store)

    result = await usecase.execute(
        GetConversationHistoryInput(
            session_id="session-001",
            buyer_id="buyer-001",
            limit=2,
        )
    )

    assert result.session_id == "session-001"
    assert [turn.content for turn in result.turns] == [
        "turn-1",
        "turn-2",
    ]
    assert result.turns[0].model == "test-model"
    assert result.turns[1].latency_ms == 2


@pytest.mark.asyncio
async def test_history_rejects_missing_session() -> None:
    usecase = GetConversationHistoryUseCase(
        InMemoryConversationStore(),
    )

    with pytest.raises(ConversationNotFoundError):
        await usecase.execute(
            GetConversationHistoryInput(
                session_id="missing",
                buyer_id="buyer-001",
            )
        )


@pytest.mark.asyncio
async def test_history_rejects_another_buyer() -> None:
    store = InMemoryConversationStore()
    await store.touch_session(
        "session-private",
        "buyer-owner",
        "zh-CN",
        "CNY",
    )
    usecase = GetConversationHistoryUseCase(store)

    with pytest.raises(ConversationOwnershipError):
        await usecase.execute(
            GetConversationHistoryInput(
                session_id="session-private",
                buyer_id="buyer-intruder",
            )
        )


@pytest.mark.parametrize(
    "values",
    [
        {"session_id": "", "buyer_id": "buyer-001"},
        {"session_id": "session-001", "buyer_id": ""},
        {"session_id": "session-001", "buyer_id": "buyer-001", "limit": 0},
        {"session_id": "session-001", "buyer_id": "buyer-001", "limit": 101},
    ],
)
def test_history_input_rejects_invalid_values(values: dict) -> None:
    with pytest.raises(ValueError):
        GetConversationHistoryInput(**values)


@pytest.mark.asyncio
async def test_history_reads_turn_written_by_orchestrator() -> None:
    conversation_store = InMemoryConversationStore()
    model = ScriptedChatModel(
        responses=[
            ChatResponse(
                content=[TextBlock(type="text", text="Agent reply")],
                is_last=True,
            )
        ]
    )
    factory = MainAgentFactory(model=model, tools=[])
    sessions = SessionRegistry(factory, InMemorySessionStore())
    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
        event_bus=InMemoryTradeEventBus(),
        conversation_store=conversation_store,
    )
    await orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-e2e",
            buyer_id="buyer-001",
            locale="zh-CN",
            currency="CNY",
            raw_query="Buyer question",
        )
    )

    result = await GetConversationHistoryUseCase(
        conversation_store,
    ).execute(
        GetConversationHistoryInput(
            session_id="session-e2e",
            buyer_id="buyer-001",
        )
    )

    assert [turn.content for turn in result.turns] == [
        "Buyer question",
        "Agent reply",
    ]
