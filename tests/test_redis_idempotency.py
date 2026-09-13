import pytest

from app.infrastructure.cache.redis_idempotency import (
    RedisIdempotency,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool,
    ) -> bool:
        if nx and key in self.values:
            return False

        self.values[key] = value
        return True

    async def get(self, key: str):
        return self.values.get(key)

    async def eval(
        self,
        script: str,
        number_of_keys: int,
        key: str,
        expected_value: str,
    ) -> int:
        assert "redis.call('get'" in script
        assert number_of_keys == 1

        if self.values.get(key) != expected_value:
            return 0

        del self.values[key]
        return 1


@pytest.mark.asyncio
async def test_claim_creates_and_reuses_the_winning_value() -> None:
    redis = FakeRedis()
    idempotency = RedisIdempotency(redis)

    first = await idempotency.claim("request", "task-1", 60)
    second = await idempotency.claim("request", "task-2", 60)

    assert first.value == "task-1"
    assert first.acquired is True
    assert second.value == "task-1"
    assert second.acquired is False


@pytest.mark.asyncio
async def test_release_only_deletes_the_callers_reservation() -> None:
    redis = FakeRedis()
    redis.values["request"] = "task-1"
    idempotency = RedisIdempotency(redis)

    assert await idempotency.release("request", "task-2") is False
    assert redis.values["request"] == "task-1"
    assert await idempotency.release("request", "task-1") is True
    assert "request" not in redis.values


@pytest.mark.asyncio
async def test_claim_retries_when_a_key_expires_between_set_and_get() -> None:
    class ExpiringRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.first_set = True

        async def set(self, key, value, *, ex, nx):
            if self.first_set:
                self.first_set = False
                return False

            return await super().set(key, value, ex=ex, nx=nx)

    idempotency = RedisIdempotency(ExpiringRedis())

    claim = await idempotency.claim("request", "task-1", 60)

    assert claim.value == "task-1"
    assert claim.acquired is True


@pytest.mark.asyncio
async def test_claim_propagates_redis_errors() -> None:
    class BrokenRedis(FakeRedis):
        async def set(self, key, value, *, ex, nx):
            raise ConnectionError("redis unavailable")

    idempotency = RedisIdempotency(BrokenRedis())

    with pytest.raises(ConnectionError, match="redis unavailable"):
        await idempotency.claim("request", "task-1", 60)
