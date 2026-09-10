from pathlib import Path

from app.domain.session.ports.session_store import (
    SessionStore,
)
from app.infrastructure.persistence.file_names import (
    safe_storage_name,
)


class JsonFileSessionStore(SessionStore):
    """Save every AgentState snapshot as a JSON file."""

    def __init__(self, data_dir: Path) -> None:
        self._session_dir = data_dir / "sessions"
        self._session_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _path(self, session_id: str) -> Path:
        return self._session_dir / (
            f"{safe_storage_name(session_id)}.json"
        )

    async def save(
        self,
        session_id: str,
        state_json: str,
    ) -> None:
        self._path(session_id).write_text(
            state_json,
            encoding="utf-8",
        )

    async def load(
        self,
        session_id: str,
    ) -> str | None:
        path = self._path(session_id)

        if not path.exists():
            return None

        return path.read_text(
            encoding="utf-8",
        )
    