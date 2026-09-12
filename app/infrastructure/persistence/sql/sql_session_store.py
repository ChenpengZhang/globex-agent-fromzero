from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.domain.session.ports.session_store import (
    SessionStore,
)
from app.infrastructure.persistence.sql.tables import (
    AgentSessionStateRow,
)


class SqlSessionStore(SessionStore):
    """
    Persist AgentState snapshots in SQLite.
    We leave the exceptions to the application layer,
    to let the application process to determine 
    how to handle it, since it can vary depending on
    usecase. 
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def save(
        self,
        session_id: str,
        state_json: str,
    ) -> None:
        statement = (
            insert(AgentSessionStateRow)
            .values(
                session_id=session_id,
                snapshot_json=state_json,
            )
            .on_conflict_do_update(
                index_elements=[
                    AgentSessionStateRow.session_id,
                ],
                set_={
                    "snapshot_json": state_json,
                    "updated_at": func.now(),
                    # Not able to self refresh when upserting.
                },
            )
        )

        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()

    async def load(
        self,
        session_id: str,
    ) -> str | None:
        async with self._session_factory() as session:
            row = await session.get(
                AgentSessionStateRow,
                session_id,
            )

        if row is None:
            return None

        return row.snapshot_json
