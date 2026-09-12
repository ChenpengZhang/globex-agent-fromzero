from dataclasses import dataclass, field
from datetime import datetime, timezone


VALID_PREFERENCE_KINDS = (
    "like",
    "dislike",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BuyerPreference:
    """A durable preference belonging to one buyer."""

    buyer_id: str
    kind: str
    statement: str
    created_at: str = field(
        default_factory=_now_iso,
    )

    def __post_init__(self) -> None:
        buyer_id = self.buyer_id.strip()
        statement = self.statement.strip()

        if not buyer_id:
            raise ValueError(
                "BuyerPreference.buyer_id cannot be empty",
            )

        if self.kind not in VALID_PREFERENCE_KINDS:
            raise ValueError(
                "BuyerPreference.kind must be one of "
                f"{VALID_PREFERENCE_KINDS}",
            )

        if not statement:
            raise ValueError(
                "BuyerPreference.statement cannot be empty",
            )

        object.__setattr__(
            self,
            "buyer_id",
            buyer_id,
        )
        object.__setattr__(
            self,
            "statement",
            statement,
        )
        