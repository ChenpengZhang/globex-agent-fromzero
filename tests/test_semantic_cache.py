from typing import Any

import pytest

from app.infrastructure.cache.semantic_cache import (
    SemanticCache,
    is_cacheable_query,
)


class MemoryCache:
    def __init__(
        self,
        *,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[str] = []
        self.fail_reads = False
        self.fail_writes = False

    async def get_json(self, key: str) -> Any | None:
        self.get_calls.append(key)

        if self.fail_reads:
            raise RuntimeError("cache read unavailable")

        return self.values.get(key)

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl_seconds: int,
    ) -> None:
        self.set_calls.append(key)

        if self.fail_writes:
            raise RuntimeError("cache write unavailable")

        self.values[key] = value
        self.ttls[key] = ttl_seconds


class SemanticEmbeddingClient:
    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}
        self.calls: list[str] = []
        self.fail = False

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)

        if self.fail:
            raise RuntimeError("embedding unavailable")

        return self.vectors.get(text, [1.0, 0.0])

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return [
            await self.embed(text)
            for text in texts
        ]


def build_semantic_cache(
    *,
    cache: MemoryCache | None = None,
    embedder: SemanticEmbeddingClient | None = None,
    enabled: bool = True,
    threshold: float = 0.95,
    namespace: str = "model-A:prompt-v1",
) -> tuple[
    SemanticCache,
    MemoryCache,
    SemanticEmbeddingClient,
]:
    memory_cache = cache or MemoryCache()
    embedding_client = embedder or SemanticEmbeddingClient()
    semantic_cache = SemanticCache(
        cache=memory_cache,  # type: ignore[arg-type]
        embedder=embedding_client,  # type: ignore[arg-type]
        threshold=threshold,
        enabled=enabled,
        namespace=namespace,
    )
    return semantic_cache, memory_cache, embedding_client


@pytest.mark.parametrize(
    "query",
    [
        "确认购买 P1001",
        "取消我的订单",
        "订单号 GBX-000001",
        "刚才那个多少钱",
        "我想买一个旅行包",
        "请记住我喜欢轻量化产品",
        "撤回我的长期偏好",
        "Please cancel my order",
        "checkout this item",
        "Remember that I prefer minimalist design",
    ],
)
def test_write_and_context_dependent_queries_are_not_cacheable(
    query: str,
) -> None:
    assert is_cacheable_query(query) is False


@pytest.mark.parametrize(
    "query",
    [
        "推荐适合登机的轻量旅行包",
        "如何选择不锈钢水杯",
        "Compare lightweight travel bags",
    ],
)
def test_independent_read_queries_are_cacheable(
    query: str,
) -> None:
    assert is_cacheable_query(query) is True


@pytest.mark.asyncio
async def test_remember_and_lookup_semantically_similar_query() -> None:
    semantic, cache, embedder = build_semantic_cache()
    embedder.vectors.update(
        {
            "推荐轻量旅行包": [1.0, 0.0],
            "想找轻便旅行背包": [0.99, 0.01],
        }
    )

    await semantic.remember(
        buyer_id="buyer-001",
        query="推荐轻量旅行包。",
        reply="推荐 P1001。",
        has_history=False,
    )
    hit = await semantic.lookup(
        buyer_id="buyer-001",
        query="想找轻便旅行背包",
        has_history=False,
    )

    assert hit is not None
    assert hit.reply == "推荐 P1001。"
    assert hit.matched_query == "推荐轻量旅行包"
    assert hit.similarity >= 0.95
    assert set(cache.ttls.values()) == {24 * 60 * 60}


@pytest.mark.asyncio
async def test_below_threshold_is_a_cache_miss() -> None:
    semantic, _, embedder = build_semantic_cache()
    embedder.vectors.update(
        {
            "推荐旅行包": [1.0, 0.0],
            "如何选择咖啡机": [0.0, 1.0],
        }
    )
    await semantic.remember(
        "buyer-001",
        "推荐旅行包",
        "推荐 P1001",
        False,
    )

    hit = await semantic.lookup(
        "buyer-001",
        "如何选择咖啡机",
        False,
    )

    assert hit is None


@pytest.mark.asyncio
async def test_cache_entries_are_isolated_by_buyer() -> None:
    semantic, _, embedder = build_semantic_cache()
    await semantic.remember(
        "buyer-A",
        "推荐旅行包",
        "A 的个性化回复",
        False,
    )
    calls_after_write = len(embedder.calls)

    hit = await semantic.lookup(
        "buyer-B",
        "推荐旅行包",
        False,
    )

    assert hit is None
    assert len(embedder.calls) == calls_after_write


@pytest.mark.asyncio
async def test_preference_scope_change_invalidates_old_reply() -> None:
    semantic, _, embedder = build_semantic_cache()
    await semantic.remember(
        buyer_id="buyer-001",
        query="推荐水杯",
        reply="推荐塑料水杯",
        has_history=False,
        scope="pref-before",
    )
    calls_after_write = len(embedder.calls)

    hit = await semantic.lookup(
        buyer_id="buyer-001",
        query="推荐水杯",
        has_history=False,
        scope="pref-after",
    )

    assert hit is None
    assert len(embedder.calls) == calls_after_write


@pytest.mark.asyncio
async def test_namespace_change_invalidates_old_reply() -> None:
    cache = MemoryCache()
    old_cache, _, _ = build_semantic_cache(
        cache=cache,
        namespace="model-A:prompt-v1",
    )
    new_cache, _, new_embedder = build_semantic_cache(
        cache=cache,
        namespace="model-A:prompt-v2",
    )
    await old_cache.remember(
        "buyer-001",
        "推荐旅行包",
        "旧提示词生成的回复",
        False,
    )

    hit = await new_cache.lookup(
        "buyer-001",
        "推荐旅行包",
        False,
    )

    assert hit is None
    assert new_embedder.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "reply", "has_history"),
    [
        ("刚才那个多少钱", "上下文回复", False),
        ("确认购买 P1001", "订单已创建", False),
        ("推荐旅行包", "多轮回复", True),
        ("推荐旅行包", "[error] 模型不可用", False),
        ("推荐旅行包", "", False),
    ],
)
async def test_unsafe_or_invalid_replies_are_not_stored(
    query: str,
    reply: str,
    has_history: bool,
) -> None:
    semantic, cache, embedder = build_semantic_cache()

    await semantic.remember(
        "buyer-001",
        query,
        reply,
        has_history,
    )

    assert cache.values == {}
    assert embedder.calls == []


@pytest.mark.asyncio
async def test_existing_query_is_replaced_and_bucket_is_bounded() -> None:
    semantic, cache, _ = build_semantic_cache()

    for index in range(32):
        await semantic.remember(
            "buyer-001",
            f"推荐旅行装备 {index}",
            f"reply-{index}",
            False,
        )

    await semantic.remember(
        "buyer-001",
        "推荐旅行装备 31",
        "updated-reply",
        False,
    )

    bucket = next(iter(cache.values.values()))

    assert len(bucket) == 30
    matching = [
        entry
        for entry in bucket
        if entry["query"] == "推荐旅行装备 31"
    ]
    assert matching == [
        {
            "query": "推荐旅行装备 31",
            "reply": "updated-reply",
            "vector": [1.0, 0.0],
        }
    ]


@pytest.mark.asyncio
async def test_redis_and_embedding_failures_degrade_to_miss() -> None:
    cache = MemoryCache()
    embedder = SemanticEmbeddingClient()
    semantic, _, _ = build_semantic_cache(
        cache=cache,
        embedder=embedder,
    )

    cache.fail_reads = True
    assert await semantic.lookup(
        "buyer-001",
        "推荐旅行包",
        False,
    ) is None

    cache.fail_reads = False
    await semantic.remember(
        "buyer-001",
        "推荐旅行包",
        "推荐 P1001",
        False,
    )
    embedder.fail = True

    assert await semantic.lookup(
        "buyer-001",
        "推荐旅行包",
        False,
    ) is None


@pytest.mark.asyncio
async def test_disabled_cache_does_no_work() -> None:
    cache = MemoryCache(enabled=False)
    semantic, _, embedder = build_semantic_cache(
        cache=cache,
    )

    await semantic.remember(
        "buyer-001",
        "推荐旅行包",
        "推荐 P1001",
        False,
    )
    hit = await semantic.lookup(
        "buyer-001",
        "推荐旅行包",
        False,
    )

    assert semantic.enabled is False
    assert hit is None
    assert cache.get_calls == []
    assert cache.set_calls == []
    assert embedder.calls == []
