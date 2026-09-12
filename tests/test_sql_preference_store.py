from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.domain.buyer.preference import BuyerPreference
from app.infrastructure.persistence.sql.database import (
    bootstrap_schema,
    create_database_engine,
)
from app.infrastructure.persistence.sql.sql_preference_store import (
    SqlPreferenceStore,
)
from app.infrastructure.persistence.sql.tables import (
    BuyerPreferenceRow,
)


@asynccontextmanager
async def _preference_store(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[
        SqlPreferenceStore,
        async_sessionmaker[AsyncSession],
        AsyncEngine,
    ]
]:
    engine = create_database_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'preferences.db'}"
    )
    await bootstrap_schema(engine)
    factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    try:
        yield SqlPreferenceStore(factory), factory, engine
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_preference_store_round_trip_in_write_order(
    tmp_path: Path,
) -> None:
    async with _preference_store(tmp_path) as (store, _, _):
        assert await store.list_by_buyer("buyer-001") == []

        expected = [
            BuyerPreference(
                buyer_id="buyer-001",
                kind="like",
                statement="喜欢小众设计",
                created_at="2026-09-10T12:00:00+00:00",
            ),
            BuyerPreference(
                buyer_id="buyer-001",
                kind="dislike",
                statement="不要塑料材质",
                created_at="2026-09-10T12:01:00+00:00",
            ),
        ]

        for preference in expected:
            await store.append(preference)

        assert await store.list_by_buyer("buyer-001") == expected


@pytest.mark.asyncio
async def test_sql_preference_append_is_idempotent_per_identity(
    tmp_path: Path,
) -> None:
    async with _preference_store(tmp_path) as (store, _, _):
        preference = BuyerPreference(
            buyer_id="buyer-001",
            kind="like",
            statement="喜欢小众设计",
        )

        await store.append(preference)
        await store.append(preference)
        await store.append(
            BuyerPreference(
                buyer_id="buyer-001",
                kind="dislike",
                statement="喜欢小众设计",
            )
        )

        restored = await store.list_by_buyer("buyer-001")

        assert [(item.kind, item.statement) for item in restored] == [
            ("like", "喜欢小众设计"),
            ("dislike", "喜欢小众设计"),
        ]


@pytest.mark.asyncio
async def test_sql_preferences_are_isolated_by_buyer(
    tmp_path: Path,
) -> None:
    async with _preference_store(tmp_path) as (store, _, _):
        await store.append(
            BuyerPreference(
                buyer_id="buyer-A",
                kind="dislike",
                statement="不要塑料材质",
            )
        )
        await store.append(
            BuyerPreference(
                buyer_id="buyer-B",
                kind="like",
                statement="喜欢塑料材质",
            )
        )

        buyer_a = await store.list_by_buyer("buyer-A")
        buyer_b = await store.list_by_buyer("buyer-B")

        assert [item.statement for item in buyer_a] == [
            "不要塑料材质",
        ]
        assert [item.statement for item in buyer_b] == [
            "喜欢塑料材质",
        ]


@pytest.mark.asyncio
async def test_sql_preference_delete_is_exact_and_buyer_scoped(
    tmp_path: Path,
) -> None:
    async with _preference_store(tmp_path) as (store, _, _):
        for preference in [
            BuyerPreference(
                buyer_id="buyer-001",
                kind="like",
                statement="不要塑料",
            ),
            BuyerPreference(
                buyer_id="buyer-001",
                kind="dislike",
                statement="不要塑料",
            ),
            BuyerPreference(
                buyer_id="buyer-001",
                kind="dislike",
                statement="不要塑料包装",
            ),
            BuyerPreference(
                buyer_id="buyer-002",
                kind="dislike",
                statement="不要塑料",
            ),
        ]:
            await store.append(preference)

        deleted = await store.delete(
            "buyer-001",
            "不要塑料",
        )
        deleted_again = await store.delete(
            "buyer-001",
            "不要塑料",
        )

        assert deleted is True
        assert deleted_again is False
        assert [
            item.statement
            for item in await store.list_by_buyer("buyer-001")
        ] == ["不要塑料包装"]
        assert [
            item.statement
            for item in await store.list_by_buyer("buyer-002")
        ] == ["不要塑料"]


@pytest.mark.asyncio
async def test_database_rejects_invalid_preference_kind(
    tmp_path: Path,
) -> None:
    async with _preference_store(tmp_path) as (_, factory, _):
        async with factory() as session:
            session.add(
                BuyerPreferenceRow(
                    buyer_id="buyer-001",
                    kind="temporary",
                    statement="本次临时要求",
                    created_at="2026-09-10T12:00:00+00:00",
                )
            )

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
