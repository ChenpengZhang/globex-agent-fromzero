from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IdempotencyClaim:
    value: str
    acquired: bool


class IdempotencyStore(Protocol):
    """Reserve stable results for safely retried application requests."""

    async def claim(
        self,
        key: str,
        proposed_value: str,
        ttl_seconds: int,
    ) -> IdempotencyClaim:
        ...

    async def release(
        self,
        key: str,
        expected_value: str,
    ) -> bool:
        ...
