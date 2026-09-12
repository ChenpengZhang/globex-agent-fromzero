from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from app.domain.buyer.preference import BuyerPreference


def test_buyer_preference_normalizes_identity_and_statement() -> None:
    preference = BuyerPreference(
        buyer_id="  buyer-001  ",
        kind="like",
        statement="  喜欢小众设计  ",
    )

    assert preference.buyer_id == "buyer-001"
    assert preference.statement == "喜欢小众设计"


def test_buyer_preference_uses_utc_creation_time() -> None:
    preference = BuyerPreference(
        buyer_id="buyer-001",
        kind="dislike",
        statement="不要塑料材质",
    )

    created_at = datetime.fromisoformat(preference.created_at)

    assert created_at.utcoffset() is not None
    assert created_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("kind", ["", "LIKE", "neutral", "temporary"])
def test_buyer_preference_rejects_unknown_kind(kind: str) -> None:
    with pytest.raises(ValueError, match="kind"):
        BuyerPreference(
            buyer_id="buyer-001",
            kind=kind,
            statement="喜欢小众设计",
        )


@pytest.mark.parametrize(
    ("buyer_id", "statement"),
    [
        ("", "喜欢小众设计"),
        ("   ", "喜欢小众设计"),
        ("buyer-001", ""),
        ("buyer-001", "   "),
    ],
)
def test_buyer_preference_requires_identity_and_statement(
    buyer_id: str,
    statement: str,
) -> None:
    with pytest.raises(ValueError):
        BuyerPreference(
            buyer_id=buyer_id,
            kind="like",
            statement=statement,
        )


def test_buyer_preference_is_immutable() -> None:
    preference = BuyerPreference(
        buyer_id="buyer-001",
        kind="like",
        statement="喜欢小众设计",
    )

    with pytest.raises(FrozenInstanceError):
        preference.statement = "changed"  # type: ignore[misc]
