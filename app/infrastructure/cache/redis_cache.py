import json
import logging
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis


logger = logging.getLogger(__name__)


class RedisCache:
    """
    Thin fault-tolerant wrapper around the async Redis client.

    Cache failures must not block the main business workflow.
    An empty URL creates a disabled cache.
    """

    def __init__(
        self,
        redis_url: str = "",
    ) -> None:
        self._client: Redis | None = None

        if not redis_url:
            return

        try:
            self._client = aioredis.from_url(
                redis_url,
                decode_responses=True,
            )
        except Exception as error:
            logger.warning(
                "Redis initialization failed; "
                "cache is disabled: %s",
                error,
            )

    @property
    def enabled(self) -> bool:
        """
        Return whether a Redis client is configured.

        This does not guarantee that the Redis server is reachable.
        Use ping() for a connectivity check.
        """

        return self._client is not None

    @property
    def client(self) -> Redis | None:
        """
        Expose the raw client for Redis-specific infrastructure.

        Ordinary cache users should use the safe wrapper methods.
        Redis Stream and Pub/Sub adapters will need the raw client.
        """

        return self._client

    async def ping(self) -> bool:
        client = self._client

        if client is None:
            return False

        try:
            return bool(await client.ping())
        except Exception:
            return False

    async def get_json(
        self,
        key: str,
    ) -> Any | None:
        client = self._client

        if client is None:
            return None

        try:
            raw_value = await client.get(key)
        except Exception as error:
            logger.warning(
                "Redis read failed; treating it as a cache miss: "
                "%s (%s)",
                key,
                error,
            )
            return None

        if raw_value is None:
            return None

        try:
            return json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            await self.delete(key)
            return None

    async def get_raw(
        self,
        key: str,
    ) -> str | None:
        """
        Read a plain string without JSON decoding.

        Idempotency keys store raw task IDs, so they must not use
        get_json().
        """

        client = self._client

        if client is None:
            return None

        try:
            value = await client.get(key)
        except Exception as error:
            logger.warning(
                "Redis raw read failed; treating it as a miss: "
                "%s (%s)",
                key,
                error,
            )
            return None

        return value if isinstance(value, str) else None

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl_seconds: int,
    ) -> None:
        client = self._client

        if client is None:
            return

        try:
            await client.set(
                key,
                json.dumps(
                    value,
                    ensure_ascii=False,
                ),
                ex=ttl_seconds,
            )
        except Exception as error:
            logger.warning(
                "Redis write failed; skipping cache update: "
                "%s (%s)",
                key,
                error,
            )

    async def delete(
        self,
        key: str,
    ) -> None:
        client = self._client

        if client is None:
            return

        try:
            await client.delete(key)
        except Exception as error:
            logger.warning(
                "Redis delete failed; ignoring cache cleanup: "
                "%s (%s)",
                key,
                error,
            )

    async def set_if_absent(
        self,
        key: str,
        value: str,
        ttl_seconds: int,
    ) -> bool:
        """
        Atomically write a value only when the key is absent.

        A disabled or unavailable cache returns True so an optional
        idempotency mechanism cannot block the business workflow.
        """

        client = self._client

        if client is None:
            return True

        try:
            result = await client.set(
                key,
                value,
                ex=ttl_seconds,
                nx=True,
            )
            return bool(result)
        except Exception as error:
            logger.warning(
                "Redis SET NX failed; allowing the request: "
                "%s (%s)",
                key,
                error,
            )
            return True

    async def close(self) -> None:
        client = self._client
        self._client = None

        if client is None:
            return

        try:
            await client.aclose()
        except Exception as error:
            logger.warning(
                "Redis close failed: %s",
                error,
            )
