from typing import Any

from app.application.idempotency import IdempotencyClaim


class RedisIdempotency:
    """Strict Redis-backed ownership for request idempotency keys."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def claim(
        self,
        key: str,
        proposed_value: str,
        ttl_seconds: int,
    ) -> IdempotencyClaim:
        """Return the winning value, creating it when the key is free."""

        for _ in range(2):
            acquired = await self._client.set(
                key,
                proposed_value,
                ex=ttl_seconds,
                nx=True,
            )

            if acquired:
                return IdempotencyClaim(
                    value=proposed_value,
                    acquired=True,
                )

            existing = await self._client.get(key)

            if isinstance(existing, bytes):
                existing = existing.decode("utf-8")

            if isinstance(existing, str) and existing:
                return IdempotencyClaim(
                    value=existing,
                    acquired=False,
                )

        raise RuntimeError(
            "Idempotency key changed while it was being claimed"
        )

    async def release(
        self,
        key: str,
        expected_value: str,
    ) -> bool:
        """Delete a reservation only when it is still owned by the caller."""

        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        deleted = await self._client.eval(
            script,
            1,
            key,
            expected_value,
        )
        return bool(deleted)
