from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.persistence.sql.database import (
    bootstrap_schema,
    create_database_engine,
)
from app.infrastructure.persistence.sql.tables import (
    ConversationMessageRow,
    ConversationSessionRow,
)


def _database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'globex.db'}"


def test_database_engine_rejects_unsupported_driver() -> None:
    with pytest.raises(ValueError, match=r"sqlite\+aiosqlite"):
        create_database_engine("postgresql+asyncpg://localhost/globex")


@pytest.mark.asyncio
async def test_bootstrap_creates_missing_database_directory(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "nested" / "data" / "globex.db"
    engine = create_database_engine(
        f"sqlite+aiosqlite:///{database_path}"
    )

    try:
        assert not database_path.parent.exists()

        await bootstrap_schema(engine)

        assert database_path.is_file()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_and_preserves_data(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(_database_url(tmp_path))

    try:
        await bootstrap_schema(engine)

        async with engine.begin() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(
                    inspect(sync_connection).get_table_names()
                )
            )
            await connection.execute(
                ConversationSessionRow.__table__.insert().values(
                    session_id="session-001",
                    buyer_id="buyer-001",
                    locale="zh-CN",
                    currency="CNY",
                )
            )

        await bootstrap_schema(engine)

        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            restored = await session.scalar(
                select(ConversationSessionRow).where(
                    ConversationSessionRow.session_id == "session-001"
                )
            )

        assert table_names == {
            "agent_session_states",
            "conversation_events",
            "conversation_messages",
            "conversation_sessions",
        }
        assert restored is not None
        assert restored.buyer_id == "buyer-001"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_connection_pragmas_are_enabled(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(_database_url(tmp_path))

    try:
        async with engine.connect() as connection:
            foreign_keys = await connection.scalar(
                text("PRAGMA foreign_keys")
            )
            journal_mode = await connection.scalar(
                text("PRAGMA journal_mode")
            )
            busy_timeout = await connection.scalar(
                text("PRAGMA busy_timeout")
            )

        assert foreign_keys == 1
        assert journal_mode == "wal"
        assert busy_timeout == 5000
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_message_foreign_key_is_enforced(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(_database_url(tmp_path))
    await bootstrap_schema(engine)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session:
            session.add(
                ConversationMessageRow(
                    session_id="missing-session",
                    turn_index=0,
                    buyer_id="buyer-001",
                    role="buyer",
                    content="hello",
                    created_at=datetime.now(timezone.utc),
                )
            )

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_index_is_unique_inside_one_session(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(_database_url(tmp_path))
    await bootstrap_schema(engine)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session:
            session.add(
                ConversationSessionRow(
                    session_id="session-001",
                    buyer_id="buyer-001",
                    locale="zh-CN",
                    currency="CNY",
                )
            )
            await session.flush()
            session.add_all(
                [
                    ConversationMessageRow(
                        session_id="session-001",
                        turn_index=0,
                        buyer_id="buyer-001",
                        role="buyer",
                        content="first",
                        created_at=datetime.now(timezone.utc),
                    ),
                    ConversationMessageRow(
                        session_id="session-001",
                        turn_index=0,
                        buyer_id="buyer-001",
                        role="agent",
                        content="duplicate index",
                        created_at=datetime.now(timezone.utc),
                    ),
                ]
            )

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await engine.dispose()
