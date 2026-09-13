import json

import pytest

import app.infrastructure.cache.redis_cache as redis_cache_module
from app.infrastructure.cache.redis_cache import RedisCache


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.deleted: list[str] = []
        self.failures: set[str] = set()
        self.closed = False

    async def ping(self) -> bool:
        self._raise_if_failed("ping")
        return True

    async def get(self, key: str) -> str | None:
        self._raise_if_failed("get")
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> bool | None:
        self._raise_if_failed("set")

        if nx and key in self.values:
            return None

        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def delete(self, key: str) -> int:
        self._raise_if_failed("delete")
        self.deleted.append(key)
        return int(self.values.pop(key, None) is not None)

    async def aclose(self) -> None:
        self._raise_if_failed("close")
        self.closed = True

    def _raise_if_failed(self, operation: str) -> None:
        if operation in self.failures:
            raise RuntimeError(f"{operation} unavailable")


def configured_cache(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeRedisClient | None = None,
) -> tuple[RedisCache, FakeRedisClient]:
    fake_client = client or FakeRedisClient()

    def from_url(
        redis_url: str,
        *,
        decode_responses: bool,
    ) -> FakeRedisClient:
        assert redis_url == "redis://localhost:6379/0"
        assert decode_responses is True
        return fake_client

    monkeypatch.setattr(
        redis_cache_module.aioredis,
        "from_url",
        from_url,
    )

    return (
        RedisCache("redis://localhost:6379/0"),
        fake_client,
    )


@pytest.mark.asyncio
async def test_empty_url_creates_safe_disabled_cache() -> None:
    cache = RedisCache()

    assert cache.enabled is False
    assert cache.client is None
    assert await cache.ping() is False
    assert await cache.get_json("missing") is None
    assert await cache.get_raw("missing") is None
    assert await cache.set_if_absent("idem", "task-1", 60) is True

    await cache.set_json("key", {"value": 1}, 60)
    await cache.delete("key")
    await cache.close()


@pytest.mark.asyncio
async def test_configured_cache_exposes_client_and_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, client = configured_cache(monkeypatch)

    assert cache.enabled is True
    assert cache.client is client
    assert await cache.ping() is True


@pytest.mark.asyncio
async def test_json_round_trip_preserves_structure_and_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, client = configured_cache(monkeypatch)
    value = {
        "buyer": "买家-001",
        "vector": [0.1, -0.2, 0.3],
        "active": True,
    }

    await cache.set_json("profile", value, 90)

    assert json.loads(client.values["profile"]) == value
    assert client.ttls["profile"] == 90
    assert await cache.get_json("profile") == value
    assert isinstance(await cache.get_raw("profile"), str)


@pytest.mark.asyncio
async def test_invalid_json_is_deleted_and_treated_as_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, client = configured_cache(monkeypatch)
    client.values["corrupt"] = "not-json"

    result = await cache.get_json("corrupt")

    assert result is None
    assert "corrupt" in client.deleted
    assert "corrupt" not in client.values


@pytest.mark.asyncio
async def test_set_if_absent_is_atomic_for_existing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, client = configured_cache(monkeypatch)

    first = await cache.set_if_absent(
        "idem:request",
        "task-first",
        600,
    )
    second = await cache.set_if_absent(
        "idem:request",
        "task-second",
        600,
    )

    assert first is True
    assert second is False
    assert client.values["idem:request"] == "task-first"
    assert client.ttls["idem:request"] == 600


@pytest.mark.asyncio
async def test_operation_failures_do_not_escape_to_business_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRedisClient()
    client.failures.update(
        {
            "ping",
            "get",
            "set",
            "delete",
        }
    )
    cache, _ = configured_cache(monkeypatch, client)

    assert await cache.ping() is False
    assert await cache.get_json("key") is None
    assert await cache.get_raw("key") is None
    assert await cache.set_if_absent("idem", "task", 60) is True

    await cache.set_json("key", {"value": 1}, 60)
    await cache.delete("key")


@pytest.mark.asyncio
async def test_close_disables_cache_even_when_client_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRedisClient()
    client.failures.add("close")
    cache, _ = configured_cache(monkeypatch, client)

    await cache.close()

    assert cache.enabled is False
    assert cache.client is None


def test_invalid_url_disables_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_from_url(*args, **kwargs):
        raise ValueError("invalid URL")

    monkeypatch.setattr(
        redis_cache_module.aioredis,
        "from_url",
        failing_from_url,
    )

    cache = RedisCache("not-a-redis-url")

    assert cache.enabled is False
    assert cache.client is None
