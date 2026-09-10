import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.session.ports.conversation_store import (
    ConversationEventRecord,
    ConversationStore,
    ConversationTurn,
)
from app.infrastructure.persistence.file_names import (
    safe_storage_name,
)


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonFileConversationStore(ConversationStore):
    """Store one conversation as an append-only JSONL file."""

    def __init__(self, data_dir: Path) -> None:
        self._conversation_dir = (
            data_dir / "conversations"
        )
        self._conversation_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _path(self, session_id: str) -> Path:
        return self._conversation_dir / (
            f"{safe_storage_name(session_id)}.jsonl"
        )

    def _append_records(
        self,
        session_id: str,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        with self._path(session_id).open(
            "a",
            encoding="utf-8",
        ) as handle:
            for record in records:
                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def _read_records(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        path = self._path(session_id)

        if not path.exists():
            return []

        records: list[dict[str, Any]] = []

        for line in path.read_text(
            encoding="utf-8",
        ).splitlines():
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except ValueError:
                logger.warning(
                    "Skipping invalid conversation record: %s",
                    path,
                )
                continue

            if isinstance(record, dict):
                records.append(record)

        return records

    async def touch_session(
        self,
        session_id: str,
        buyer_id: str,
        locale: str,
        currency: str,
    ) -> None:
        existing = await self.find_session(
            session_id,
        )

        if (
            existing is not None
            and existing.get("buyer_id") != buyer_id
        ):
            raise ValueError(
                "The conversation session belongs "
                "to another buyer",
            )

        now = _now_iso()
        created_at = (
            existing.get("created_at", now)
            if existing is not None
            else now
        )

        self._append_records(
            session_id,
            [
                {
                    "kind": "session",
                    "session_id": session_id,
                    "buyer_id": buyer_id,
                    "locale": locale,
                    "currency": currency,
                    "created_at": created_at,
                    "updated_at": now,
                }
            ],
        )

    async def append_turn(
        self,
        turn: ConversationTurn,
    ) -> None:
        self._append_records(
            turn.session_id,
            [
                {
                    "kind": "turn",
                    "session_id": turn.session_id,
                    "buyer_id": turn.buyer_id,
                    "role": turn.role,
                    "content": turn.content,
                    "model": turn.model,
                    "latency_ms": turn.latency_ms,
                    "created_at": turn.created_at,
                }
            ],
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

        self._append_records(
            session_id,
            [
                {
                    "kind": "event",
                    "session_id": event.session_id,
                    "type": event.type,
                    "payload": event.payload,
                    "occurred_at": event.occurred_at,
                }
                for event in events
            ],
        )

    async def list_turns(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[ConversationTurn]:
        if limit <= 0:
            return []

        turns: list[ConversationTurn] = []

        for record in self._read_records(session_id):
            if record.get("kind") != "turn":
                continue

            try:
                turns.append(
                    ConversationTurn(
                        session_id=record["session_id"],
                        buyer_id=record["buyer_id"],
                        role=record["role"],
                        content=record["content"],
                        model=record.get("model", ""),
                        latency_ms=record.get(
                            "latency_ms",
                            0,
                        ),
                        created_at=record["created_at"],
                    )
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                logger.warning(
                    "Skipping invalid conversation turn: %s",
                    session_id,
                )

        return turns[-limit:]

    async def find_session(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None

        for record in self._read_records(session_id):
            if record.get("kind") == "session":
                latest = record

        return latest
    