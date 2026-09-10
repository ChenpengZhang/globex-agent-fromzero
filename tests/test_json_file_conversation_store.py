import json
from pathlib import Path

import pytest

from app.domain.session.ports.conversation_store import (
    ConversationEventRecord,
    ConversationTurn,
)
from app.infrastructure.persistence.file_names import (
    safe_storage_name,
)
from app.infrastructure.persistence.json_file_conversation_store import (
    JsonFileConversationStore,
)


def test_safe_storage_name_prevents_sanitized_collisions() -> None:
    assert safe_storage_name("a/b") != safe_storage_name("ab")
    assert "/" not in safe_storage_name("../../session")
    assert ".." not in safe_storage_name("../../session")


@pytest.mark.asyncio
async def test_touch_session_creates_and_refreshes_metadata(
    tmp_path: Path,
) -> None:
    store = JsonFileConversationStore(tmp_path)

    await store.touch_session(
        "session-001",
        "buyer-001",
        "zh-CN",
        "CNY",
    )
    first = await store.find_session("session-001")
    await store.touch_session(
        "session-001",
        "buyer-001",
        "en-US",
        "USD",
    )
    refreshed = await store.find_session("session-001")

    assert first is not None
    assert refreshed is not None
    assert refreshed["created_at"] == first["created_at"]
    assert refreshed["updated_at"] >= first["updated_at"]
    assert refreshed["locale"] == "en-US"
    assert refreshed["currency"] == "USD"


@pytest.mark.asyncio
async def test_touch_session_rejects_another_buyer(
    tmp_path: Path,
) -> None:
    store = JsonFileConversationStore(tmp_path)
    await store.touch_session(
        "session-private",
        "buyer-owner",
        "zh-CN",
        "CNY",
    )

    with pytest.raises(ValueError, match="another buyer"):
        await store.touch_session(
            "session-private",
            "buyer-intruder",
            "zh-CN",
            "CNY",
        )


@pytest.mark.asyncio
async def test_turns_round_trip_in_write_order_with_limit(
    tmp_path: Path,
) -> None:
    store = JsonFileConversationStore(tmp_path)
    turns = [
        ConversationTurn(
            session_id="session-001",
            buyer_id="buyer-001",
            role="buyer" if index % 2 == 0 else "agent",
            content=f"turn-{index}",
            latency_ms=index,
        )
        for index in range(4)
    ]

    for turn in turns:
        await store.append_turn(turn)

    restored = await store.list_turns("session-001", limit=2)

    assert [turn.content for turn in restored] == ["turn-2", "turn-3"]
    assert await store.list_turns("session-001", limit=0) == []


@pytest.mark.asyncio
async def test_events_are_written_as_structured_json_lines(
    tmp_path: Path,
) -> None:
    store = JsonFileConversationStore(tmp_path)
    event = ConversationEventRecord(
        session_id="session-001",
        type="tool.result",
        payload={"tool": "product_search_tool", "hit_count": 2},
    )

    await store.append_events([event])

    files = list((tmp_path / "conversations").glob("*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8"))
    assert record["kind"] == "event"
    assert record["payload"]["hit_count"] == 2


@pytest.mark.asyncio
async def test_event_batch_rejects_multiple_sessions(
    tmp_path: Path,
) -> None:
    store = JsonFileConversationStore(tmp_path)
    events = [
        ConversationEventRecord(
            session_id="session-A",
            type="tool.invoke",
            payload={},
        ),
        ConversationEventRecord(
            session_id="session-B",
            type="tool.result",
            payload={},
        ),
    ]

    with pytest.raises(ValueError, match="same session"):
        await store.append_events(events)


@pytest.mark.asyncio
async def test_invalid_json_line_does_not_hide_valid_turns(
    tmp_path: Path,
) -> None:
    store = JsonFileConversationStore(tmp_path)
    await store.append_turn(
        ConversationTurn(
            session_id="session-001",
            buyer_id="buyer-001",
            role="buyer",
            content="valid turn",
        )
    )
    conversation_file = next(
        (tmp_path / "conversations").glob("*.jsonl")
    )
    with conversation_file.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")

    turns = await store.list_turns("session-001")

    assert [turn.content for turn in turns] == ["valid turn"]
