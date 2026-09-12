from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.infrastructure.persistence.sql.database import (
    bootstrap_schema,
    create_database_engine,
)
from app.infrastructure.persistence.sql.sql_session_store import (
    SqlSessionStore,
)
from app.infrastructure.persistence.sql.tables import (
    AgentSessionStateRow,
)


def _database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'globex.db'}"


def _session_factory(
    database_url: str,
) -> tuple[
    async_sessionmaker[AsyncSession],
    AsyncEngine,
]:
    engine = create_database_engine(database_url)
    return (
        async_sessionmaker(
            engine,
            expire_on_commit=False,
        ),
        engine,
    )


@pytest.mark.asyncio
async def test_missing_sql_session_returns_none(
    tmp_path: Path,
) -> None:
    factory, engine = _session_factory(_database_url(tmp_path))

    try:
        await bootstrap_schema(engine)
        store = SqlSessionStore(factory)

        assert await store.load("missing-session") is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_session_snapshot_round_trip(
    tmp_path: Path,
) -> None:
    factory, engine = _session_factory(_database_url(tmp_path))

    try:
        await bootstrap_schema(engine)
        store = SqlSessionStore(factory)
        snapshot = '{"buyer_id":"buyer-001","state_json":"{}"}'

        await store.save("session-001", snapshot)

        assert await store.load("session-001") == snapshot
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_session_upsert_replaces_one_existing_row(
    tmp_path: Path,
) -> None:
    factory, engine = _session_factory(_database_url(tmp_path))

    try:
        await bootstrap_schema(engine)
        store = SqlSessionStore(factory)
        await store.save("session-001", '{"version":1}')

        async with factory() as session:
            await session.execute(
                update(AgentSessionStateRow)
                .where(
                    AgentSessionStateRow.session_id == "session-001"
                )
                .values(updated_at=datetime(2000, 1, 1))
            )
            await session.commit()

        await store.save("session-001", '{"version":2}')

        async with factory() as session:
            rows = list(
                await session.scalars(
                    select(AgentSessionStateRow).where(
                        AgentSessionStateRow.session_id == "session-001"
                    )
                )
            )
        assert len(rows) == 1
        assert rows[0].snapshot_json == '{"version":2}'
        assert rows[0].updated_at.year != 2000
    finally:
        await engine.dispose()
