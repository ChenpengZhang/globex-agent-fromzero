from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
)

from app.infrastructure.persistence.sql.tables import (
    Base,
)


def create_database_engine(
    database_url: str,
) -> AsyncEngine:
    """Create an asynchronous SQLite engine."""

    if not database_url.startswith(
        "sqlite+aiosqlite://",
    ):
        raise ValueError(
            "Only sqlite+aiosqlite is supported "
            "in this chapter",
        )

    engine = create_async_engine(
        database_url,
        echo=False,
    )

    @event.listens_for(
        engine.sync_engine,
        "connect",
    )
    def configure_sqlite(
        connection,
        _connection_record,
    ) -> None:
        cursor = connection.cursor()
        cursor.execute(
            "PRAGMA foreign_keys=ON",
        )
        cursor.execute(
            "PRAGMA journal_mode=WAL",
            # Prevent conflict from writing and reading at the same time.
        )
        cursor.execute(
            "PRAGMA busy_timeout=5000",
            # Try to wait for another process to finish writing.
        )
        cursor.close()

    return engine


async def bootstrap_schema(
    engine: AsyncEngine,
) -> None:
    """Create missing tables without deleting existing data."""

    database_path = engine.url.database

    if (
        database_path
        and database_path != ":memory:"
    ):
        Path(database_path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
        )
