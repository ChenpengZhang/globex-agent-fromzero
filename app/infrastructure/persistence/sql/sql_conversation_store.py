from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.domain.session.ports.conversation_store import (
    ConversationEventRecord,
    ConversationStore,
    ConversationTurn,
)
from app.infrastructure.persistence.sql.tables import (
    ConversationEventRow,
    ConversationMessageRow,
    ConversationSessionRow,
)


def _parse_timestamp(value: str) -> datetime:
    """Convert a Domain ISO timestamp into a database value."""

    timestamp = datetime.fromisoformat(value)

    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)


def _timestamp_to_iso(value: datetime) -> str:
    """Convert a database timestamp into a UTC ISO timestamp."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return value.isoformat()


class SqlConversationStore(ConversationStore):
    """Persist conversation records in SQLite."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def touch_session(
        self,
        session_id: str,
        buyer_id: str,
        locale: str,
        currency: str,
    ) -> None:
        async with self._session_factory.begin() as session:
            row = await session.get(
                ConversationSessionRow,
                session_id,
            )

            if row is None:
                session.add(
                    ConversationSessionRow(
                        session_id=session_id,
                        buyer_id=buyer_id,
                        locale=locale,
                        currency=currency,
                    )
                )
                return

            if row.buyer_id != buyer_id:
                raise ValueError(
                    "The conversation session belongs "
                    "to another buyer",
                )

            row.locale = locale
            row.currency = currency
            row.last_active_at = datetime.now(timezone.utc)

    async def append_turn(
        self,
        turn: ConversationTurn,
    ) -> None:
        async with self._session_factory.begin() as session:
            last_index = await session.scalar(
                select(
                    func.max(
                        ConversationMessageRow.turn_index,
                    )
                ).where(
                    ConversationMessageRow.session_id
                    == turn.session_id,
                )
            )

            next_index = (
                0
                if last_index is None
                else last_index + 1
            )

            session.add(
                ConversationMessageRow(
                    session_id=turn.session_id,
                    turn_index=next_index,
                    buyer_id=turn.buyer_id,
                    role=turn.role,
                    content=turn.content,
                    model=turn.model,
                    latency_ms=turn.latency_ms,
                    created_at=_parse_timestamp(
                        turn.created_at,
                    ),
                )
            )

    async def append_events(
        self,
        events: list[ConversationEventRecord],
    ) -> None:
        if not events:
            return

        session_id = events[0].session_id

        if any(
            event.session_id != session_id
            for event in events
        ):
            raise ValueError(
                "All events in one batch must "
                "belong to the same session",
            )

        async with self._session_factory.begin() as session:
            session.add_all(
                [
                    ConversationEventRow(
                        session_id=event.session_id,
                        type=event.type,
                        payload=event.payload,
                        occurred_at=_parse_timestamp(
                            event.occurred_at,
                        ),
                    )
                    for event in events
                ]
            )

    async def list_turns(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[ConversationTurn]:
        if limit <= 0:
            return []

        async with self._session_factory() as session:
            result = await session.scalars(
                select(ConversationMessageRow)
                .where(
                    ConversationMessageRow.session_id
                    == session_id,
                )
                .order_by(
                    ConversationMessageRow.turn_index.desc(),
                )
                .limit(limit)
            )
            rows = list(result)

        rows.reverse()

        return [
            ConversationTurn(
                session_id=row.session_id,
                buyer_id=row.buyer_id,
                role=row.role,
                content=row.content,
                model=row.model,
                latency_ms=row.latency_ms,
                created_at=_timestamp_to_iso(
                    row.created_at,
                ),
            )
            for row in rows
        ]

    async def find_session(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            row = await session.get(
                ConversationSessionRow,
                session_id,
            )

        if row is None:
            return None

        return {
            "session_id": row.session_id,
            "buyer_id": row.buyer_id,
            "locale": row.locale,
            "currency": row.currency,
            "created_at": _timestamp_to_iso(
                row.created_at,
            ),
            "updated_at": _timestamp_to_iso(
                row.last_active_at,
            ),
        }
    