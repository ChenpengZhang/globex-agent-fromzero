from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.domain.buyer.preference import (
    BuyerPreference,
)
from app.domain.buyer.ports.preference_store import (
    PreferenceStore,
)
from app.infrastructure.persistence.sql.tables import (
    BuyerPreferenceRow,
)


class SqlPreferenceStore(PreferenceStore):
    """Persist durable buyer preferences in SQLite."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def append(
        self,
        preference: BuyerPreference,
    ) -> None:
        statement = (
            insert(BuyerPreferenceRow)
            .values(
                buyer_id=preference.buyer_id,
                kind=preference.kind,
                statement=preference.statement,
                created_at=preference.created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    BuyerPreferenceRow.buyer_id,
                    BuyerPreferenceRow.kind,
                    BuyerPreferenceRow.statement,
                ],
            )
        )

        async with self._session_factory.begin() as session:
            await session.execute(statement)

    async def list_by_buyer(
        self,
        buyer_id: str,
    ) -> list[BuyerPreference]:
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(BuyerPreferenceRow)
                    .where(
                        BuyerPreferenceRow.buyer_id
                        == buyer_id,
                    )
                    .order_by(
                        BuyerPreferenceRow.id,
                    )
                )
            )

        return [
            BuyerPreference(
                buyer_id=row.buyer_id,
                kind=row.kind,
                statement=row.statement,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def delete(
        self,
        buyer_id: str,
        statement: str,
    ) -> bool:
        async with self._session_factory.begin() as session:
            result = await session.execute(
                delete(BuyerPreferenceRow).where(
                    BuyerPreferenceRow.buyer_id
                    == buyer_id,
                    BuyerPreferenceRow.statement
                    == statement,
                )
            )

        return result.rowcount > 0
