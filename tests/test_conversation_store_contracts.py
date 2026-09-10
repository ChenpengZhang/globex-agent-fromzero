from datetime import datetime

import pytest

from app.domain.session.ports.conversation_store import (
    ConversationEventRecord,
    ConversationTurn,
)


def test_conversation_turn_uses_utc_timestamp() -> None:
    turn = ConversationTurn(
        session_id="session-001",
        buyer_id="buyer-001",
        role="buyer",
        content="推荐旅行背包",
    )

    timestamp = datetime.fromisoformat(turn.created_at)

    assert timestamp.utcoffset() is not None
    assert timestamp.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("role", ["user", "assistant", "tool", ""])
def test_conversation_turn_rejects_unknown_role(role: str) -> None:
    with pytest.raises(ValueError, match="role"):
        ConversationTurn(
            session_id="session-001",
            buyer_id="buyer-001",
            role=role,
            content="content",
        )


def test_conversation_turn_rejects_negative_latency() -> None:
    with pytest.raises(ValueError, match="latency_ms"):
        ConversationTurn(
            session_id="session-001",
            buyer_id="buyer-001",
            role="agent",
            content="response",
            latency_ms=-1,
        )


def test_conversation_event_keeps_structured_payload() -> None:
    event = ConversationEventRecord(
        session_id="session-001",
        type="tool.result",
        payload={
            "tool": "product_search_tool",
            "hit_count": 3,
        },
    )

    assert event.payload["hit_count"] == 3
    assert datetime.fromisoformat(event.occurred_at).utcoffset() is not None


@pytest.mark.parametrize(
    ("session_id", "buyer_id"),
    [("", "buyer-001"), ("session-001", "")],
)
def test_conversation_turn_requires_session_and_buyer(
    session_id: str,
    buyer_id: str,
) -> None:
    with pytest.raises(ValueError):
        ConversationTurn(
            session_id=session_id,
            buyer_id=buyer_id,
            role="buyer",
            content="content",
        )
