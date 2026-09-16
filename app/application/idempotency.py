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
        """
        Indicate that the task is signed up for processing.
        Could be queuing, processing, or completed.
        """
        ...

    async def release(
        self,
        key: str,
        expected_value: str,
    ) -> bool:
        """
        If the task isn't successfully uploaded to the caller,
        we need to realease the idempotency to enable the frontend/caller
        try again. 
        """
        ...
