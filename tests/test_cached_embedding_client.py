from typing import Any

import pytest

from app.infrastructure.cache.cached_embedding_client import (
    CachedEmbeddingClient,
)


class RecordingEmbeddingClient:
    def __init__(self) -> None:
        self.batch_calls: list[list[str]] = []
        self.return_too_few = False

    async def embed(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        vectors = [
            [
                float(len(text)),
                float(sum(ord(character) for character in text)),
            ]
            for text in texts
        ]

        return vectors[:-1] if self.return_too_few else vectors


class MemoryJsonCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.fail_reads = False
        self.fail_writes = False

    async def get_json(self, key: str) -> Any | None:
        if self.fail_reads:
            raise RuntimeError("cache read unavailable")

        return self.values.get(key)

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl_seconds: int,
    ) -> None:
        if self.fail_writes:
            raise RuntimeError("cache write unavailable")

        self.values[key] = value
        self.ttls[key] = ttl_seconds


def build_cached_client(
    *,
    model: str = "embedding-model-A",
    cache: MemoryJsonCache | None = None,
    inner: RecordingEmbeddingClient | None = None,
) -> tuple[
    CachedEmbeddingClient,
    MemoryJsonCache,
    RecordingEmbeddingClient,
]:
    json_cache = cache or MemoryJsonCache()
    embedding_client = inner or RecordingEmbeddingClient()
    cached = CachedEmbeddingClient(
        inner=embedding_client,  # type: ignore[arg-type]
        cache=json_cache,  # type: ignore[arg-type]
        model=model,
    )
    return cached, json_cache, embedding_client


@pytest.mark.asyncio
async def test_miss_calls_inner_and_populates_cache() -> None:
    cached, cache, inner = build_cached_client()

    first = await cached.embed("旅行背包")
    second = await cached.embed("旅行背包")

    assert first == second
    assert inner.batch_calls == [["旅行背包"]]
    assert cached.misses == 1
    assert cached.hits == 1
    assert len(cache.values) == 1
    assert set(cache.ttls.values()) == {7 * 24 * 60 * 60}


@pytest.mark.asyncio
async def test_partial_batch_hit_only_fetches_missing_texts() -> None:
    cached, _, inner = build_cached_client()
    cached_a = await cached.embed("A")

    result = await cached.embed_batch(
        ["A", "BB", "CCC"]
    )

    assert inner.batch_calls == [
        ["A"],
        ["BB", "CCC"],
    ]
    assert result == [
        cached_a,
        [2.0, float(ord("B") * 2)],
        [3.0, float(ord("C") * 3)],
    ]
    assert cached.hits == 1
    assert cached.misses == 3


@pytest.mark.asyncio
async def test_model_name_is_part_of_cache_identity() -> None:
    cache = MemoryJsonCache()
    first, _, first_inner = build_cached_client(
        model="model-A",
        cache=cache,
    )
    second, _, second_inner = build_cached_client(
        model="model-B",
        cache=cache,
    )

    await first.embed("same text")
    await second.embed("same text")

    assert first_inner.batch_calls == [["same text"]]
    assert second_inner.batch_calls == [["same text"]]
    assert len(cache.values) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corrupt_value",
    [
        [],
        "[1.0, 2.0]",
        [1.0, "bad"],
        [True, 2.0],
    ],
)
async def test_invalid_cached_vector_is_treated_as_miss(
    corrupt_value: Any,
) -> None:
    cached, cache, inner = build_cached_client()
    cache.values[cached._key("query")] = corrupt_value

    result = await cached.embed("query")

    assert result == [5.0, float(sum(ord(c) for c in "query"))]
    assert inner.batch_calls == [["query"]]
    assert cached.misses == 1


@pytest.mark.asyncio
async def test_cache_read_and_write_failures_do_not_block_embedding() -> None:
    cached, cache, inner = build_cached_client()
    cache.fail_reads = True
    cache.fail_writes = True

    result = await cached.embed("fallback")

    assert result == [
        8.0,
        float(sum(ord(c) for c in "fallback")),
    ]
    assert inner.batch_calls == [["fallback"]]


@pytest.mark.asyncio
async def test_inner_result_count_mismatch_is_not_hidden() -> None:
    inner = RecordingEmbeddingClient()
    inner.return_too_few = True
    cached, _, _ = build_cached_client(inner=inner)

    with pytest.raises(
        RuntimeError,
        match="result count",
    ):
        await cached.embed_batch(["A", "B"])


@pytest.mark.asyncio
async def test_empty_batch_does_not_touch_inner_or_cache() -> None:
    cached, cache, inner = build_cached_client()

    result = await cached.embed_batch([])

    assert result == []
    assert inner.batch_calls == []
    assert cache.values == {}
