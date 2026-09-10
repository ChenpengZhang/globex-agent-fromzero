from pathlib import Path

import pytest

from app.infrastructure.persistence.json_file_session_store import (
    JsonFileSessionStore,
)


@pytest.mark.asyncio
async def test_missing_session_returns_none(
    tmp_path: Path,
) -> None:
    store = JsonFileSessionStore(tmp_path)

    assert await store.load("missing-session") is None


@pytest.mark.asyncio
async def test_saved_session_can_be_loaded(
    tmp_path: Path,
) -> None:
    store = JsonFileSessionStore(tmp_path)
    state_json = '{"context": [{"role": "user"}]}'

    await store.save("session-001", state_json)

    assert await store.load("session-001") == state_json


@pytest.mark.asyncio
async def test_saving_same_session_replaces_snapshot(
    tmp_path: Path,
) -> None:
    store = JsonFileSessionStore(tmp_path)

    await store.save("session-001", '{"version": 1}')
    await store.save("session-001", '{"version": 2}')

    assert await store.load("session-001") == '{"version": 2}'


@pytest.mark.asyncio
async def test_session_id_cannot_escape_session_directory(
    tmp_path: Path,
) -> None:
    store = JsonFileSessionStore(tmp_path)

    await store.save("../../outside", '{"safe": true}')

    assert not (tmp_path / "outside.json").exists()
    assert await store.load("../../outside") == '{"safe": true}'
    assert len(list((tmp_path / "sessions").glob("*.json"))) == 1
