from pathlib import Path

import pytest
from agentscope.message import TextBlock
from agentscope.model import ChatResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import (
    MainAgentOrchestrator,
    SubmitIntentInput,
)
from app.application.agents.session_registry import SessionRegistry
from app.application.usecases.get_conversation_history import (
    GetConversationHistoryInput,
    GetConversationHistoryUseCase,
)
from app.infrastructure.eventbus import InMemoryTradeEventBus
from app.infrastructure.persistence.sql.database import (
    bootstrap_schema,
    create_database_engine,
)
from app.infrastructure.persistence.sql.sql_conversation_store import (
    SqlConversationStore,
)
from app.infrastructure.persistence.sql.sql_session_store import (
    SqlSessionStore,
)
from tests.fakes import ScriptedChatModel


@pytest.mark.asyncio
async def test_agent_state_and_history_survive_database_reconnect(
    tmp_path: Path,
) -> None:
    database_url = (
        f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}"
    )
    first_engine = create_database_engine(database_url)
    await bootstrap_schema(first_engine)
    first_factory = async_sessionmaker(
        first_engine,
        expire_on_commit=False,
    )
    first_model = ScriptedChatModel(
        responses=[
            ChatResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="数据库中的回复",
                    )
                ],
                is_last=True,
            )
        ]
    )
    first_agent_factory = MainAgentFactory(
        model=first_model,
        tools=[],
    )
    first_sessions = SessionRegistry(
        first_agent_factory,
        SqlSessionStore(first_factory),
    )
    first_orchestrator = MainAgentOrchestrator(
        sessions=first_sessions,
        event_bus=InMemoryTradeEventBus(),
        conversation_store=SqlConversationStore(first_factory),
    )

    await first_orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-restart",
            buyer_id="buyer-001",
            locale="zh-CN",
            currency="CNY",
            raw_query="请记住这条消息",
        )
    )
    await first_engine.dispose()

    second_engine = create_database_engine(database_url)
    second_factory = async_sessionmaker(
        second_engine,
        expire_on_commit=False,
    )
    second_conversation_store = SqlConversationStore(
        second_factory,
    )
    second_sessions = SessionRegistry(
        MainAgentFactory(
            model=ScriptedChatModel(responses=[]),
            tools=[],
        ),
        SqlSessionStore(second_factory),
    )

    try:
        restored_session = await second_sessions.get_or_create(
            "session-restart",
            "buyer-001",
        )
        history = await GetConversationHistoryUseCase(
            second_conversation_store,
        ).execute(
            GetConversationHistoryInput(
                session_id="session-restart",
                buyer_id="buyer-001",
            )
        )

        restored_text = [
            message.get_text_content()
            for message in restored_session.agent.state.context
        ]

        assert any(
            "请记住这条消息" in (text or "")
            for text in restored_text
        )
        assert [turn.content for turn in history.turns] == [
            "请记住这条消息",
            "数据库中的回复",
        ]
    finally:
        await second_engine.dispose()
