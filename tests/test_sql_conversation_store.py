from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.domain.session.ports.conversation_store import (
    ConversationEventRecord,
    ConversationTurn,
)
from app.infrastructure.persistence.sql.database import (
    bootstrap_schema,
    create_database_engine,
)
from app.infrastructure.persistence.sql.sql_conversation_store import (
    SqlConversationStore,
)
from app.infrastructure.persistence.sql.tables import (
    ConversationEventRow,
    ConversationMessageRow,
)


@asynccontextmanager
async def _database_store(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[
        SqlConversationStore,
        async_sessionmaker[AsyncSession],
        AsyncEngine,
    ]
]:
    engine = create_database_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'globex.db'}"
    )
    await bootstrap_schema(engine)
    factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    try:
        yield SqlConversationStore(factory), factory, engine
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_conversation_session_metadata_round_trip(
    tmp_path: Path,
) -> None:
    async with _database_store(tmp_path) as (store, _, _):
        assert await store.find_session("missing-session") is None

        await store.touch_session(
            "session-001",
            "buyer-001",
            "zh-CN",
            "CNY",
        )
        first = await store.find_session("session-001")

        await store.touch_session(
            "session-001",
            "buyer-001",
            "en-US",
            "USD",
        )
        refreshed = await store.find_session("session-001")

        assert first is not None
        assert refreshed is not None
        assert refreshed["buyer_id"] == "buyer-001"
        assert refreshed["locale"] == "en-US"
        assert refreshed["currency"] == "USD"
        assert refreshed["created_at"] == first["created_at"]
        assert refreshed["updated_at"] >= first["updated_at"]


@pytest.mark.asyncio
async def test_sql_conversation_rejects_another_buyer(
    tmp_path: Path,
) -> None:
    async with _database_store(tmp_path) as (store, _, _):
        await store.touch_session(
            "session-private",
            "buyer-owner",
            "zh-CN",
            "CNY",
        )

        with pytest.raises(ValueError, match="another buyer"):
            await store.touch_session(
                "session-private",
                "buyer-intruder",
                "en-US",
                "USD",
            )

        metadata = await store.find_session("session-private")
        assert metadata is not None
        assert metadata["buyer_id"] == "buyer-owner"
        assert metadata["locale"] == "zh-CN"
        assert metadata["currency"] == "CNY"


@pytest.mark.asyncio
async def test_sql_turns_use_session_order_and_latest_limit(
    tmp_path: Path,
) -> None:
    async with _database_store(tmp_path) as (store, factory, _):
        await store.touch_session(
            "session-001",
            "buyer-001",
            "zh-CN",
            "CNY",
        )

        for index in range(4):
            await store.append_turn(
                ConversationTurn(
                    session_id="session-001",
                    buyer_id="buyer-001",
                    role="buyer" if index % 2 == 0 else "agent",
                    content=f"turn-{index}",
                    model="test-model",
                    latency_ms=index,
                    created_at=(
                        f"2026-09-10T12:00:0{index}+00:00"
                    ),
                )
            )

        restored = await store.list_turns(
            "session-001",
            limit=2,
        )
        empty = await store.list_turns(
            "session-001",
            limit=0,
        )

        async with factory() as session:
            rows = list(
                await session.scalars(
                    select(ConversationMessageRow)
                    .where(
                        ConversationMessageRow.session_id
                        == "session-001"
                    )
                    .order_by(
                        ConversationMessageRow.turn_index,
                    )
                )
            )

        assert [row.turn_index for row in rows] == [0, 1, 2, 3]
        assert [turn.content for turn in restored] == [
            "turn-2",
            "turn-3",
        ]
        assert all(isinstance(turn, ConversationTurn) for turn in restored)
        assert restored[0].created_at.endswith("+00:00")
        assert empty == []


@pytest.mark.asyncio
async def test_sql_turn_timestamp_is_normalized_to_utc(
    tmp_path: Path,
) -> None:
    async with _database_store(tmp_path) as (store, _, _):
        await store.touch_session(
            "session-001",
            "buyer-001",
            "zh-CN",
            "CNY",
        )
        await store.append_turn(
            ConversationTurn(
                session_id="session-001",
                buyer_id="buyer-001",
                role="buyer",
                content="hello",
                created_at="2026-09-10T20:30:00+08:00",
            )
        )

        turns = await store.list_turns("session-001")

        assert turns[0].created_at == "2026-09-10T12:30:00+00:00"


@pytest.mark.asyncio
async def test_sql_events_round_trip_as_structured_rows(
    tmp_path: Path,
) -> None:
    async with _database_store(tmp_path) as (store, factory, _):
        await store.touch_session(
            "session-001",
            "buyer-001",
            "zh-CN",
            "CNY",
        )
        await store.append_events(
            [
                ConversationEventRecord(
                    session_id="session-001",
                    type="tool.result",
                    payload={
                        "tool": "product_search_tool",
                        "hit_count": 2,
                    },
                )
            ]
        )

        async with factory() as session:
            rows = list(
                await session.scalars(
                    select(ConversationEventRow)
                )
            )

        assert len(rows) == 1
        assert rows[0].type == "tool.result"
        assert rows[0].payload["hit_count"] == 2


@pytest.mark.asyncio
async def test_sql_event_batch_rejects_multiple_sessions(
    tmp_path: Path,
) -> None:
    async with _database_store(tmp_path) as (store, _, _):
        events = [
            ConversationEventRecord(
                session_id="session-A",
                type="tool.invoke",
                payload={},
            ),
            ConversationEventRecord(
                session_id="session-B",
                type="tool.result",
                payload={},
            ),
        ]

        with pytest.raises(ValueError, match="same session"):
            await store.append_events(events)


@pytest.mark.asyncio
async def test_sql_event_batch_rolls_back_if_one_payload_is_invalid(
    tmp_path: Path,
) -> None:
    async with _database_store(tmp_path) as (store, factory, _):
        await store.touch_session(
            "session-001",
            "buyer-001",
            "zh-CN",
            "CNY",
        )
        events = [
            ConversationEventRecord(
                session_id="session-001",
                type="tool.invoke",
                payload={"tool": "product_search_tool"},
            ),
            ConversationEventRecord(
                session_id="session-001",
                type="tool.result",
                payload={"invalid": object()},
            ),
        ]

        with pytest.raises(StatementError):
            await store.append_events(events)

        async with factory() as session:
            rows = list(
                await session.scalars(
                    select(ConversationEventRow)
                )
            )

        assert rows == []
