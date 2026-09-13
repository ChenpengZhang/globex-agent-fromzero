import pytest

import app.composition as composition
from app.infrastructure.cache.cached_embedding_client import (
    CachedEmbeddingClient,
)
from app.application.dto.order import (
    CancelOrderInput,
    OrderItemInput,
    PlaceOrderInput,
    QueryOrderInput,
)
from app.domain.order.address import Address
from tests.fakes import (
    DeterministicEmbeddingClient,
    EmptyKnowledgeBase,
    RecordingProductVectorIndex,
    ScriptedChatModel,
    build_composition_settings,
)


@pytest.mark.asyncio
async def test_container_shares_repositories_across_order_use_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ScriptedChatModel(responses=[])
    monkeypatch.setattr(
        composition,
        "load_settings",
        build_composition_settings,
    )
    monkeypatch.setattr(
        composition,
        "create_chat_model",
        lambda settings: model,
    )
    monkeypatch.setattr(
        composition,
        "build_category_knowledge_base",
        lambda settings: EmptyKnowledgeBase(),
    )
    monkeypatch.setattr(
        composition,
        "OpenAIEmbeddingClient",
        lambda settings: DeterministicEmbeddingClient(),
    )
    monkeypatch.setattr(
        composition,
        "QdrantProductIndex",
        lambda settings: RecordingProductVectorIndex(),
    )
    container = composition.build_container()

    assert container.catalog_search._reranker is None
    assert container.cache.enabled is False
    assert container.semantic_cache.enabled is False
    assert container.task_queue is None
    assert container.idempotency is None
    assert container.event_backplane is None

    product = await container.product_repository.find_by_id("P1001")
    assert product is not None
    sku = product.find_sku("P1001-S1")
    assert sku is not None
    initial_stock = sku.stock

    placed = await container.place_order.execute(
        PlaceOrderInput(
            buyer_id="buyer-001",
            items=[
                OrderItemInput(
                    product_id="P1001",
                    sku_id="P1001-S1",
                    quantity=2,
                )
            ],
            shipping_address=Address(
                recipient_name="Alice",
                country="CN",
                state="上海",
                city="上海",
                address_line="南京西路 1 号",
                postal_code="200000",
                phone="13800000000",
            ),
        )
    )
    queried = await container.query_order.execute(
        QueryOrderInput(
            order_id=placed.order_id,
            buyer_id="buyer-001",
        )
    )

    assert sku.stock == initial_stock - 2
    assert queried.order_id == placed.order_id
    assert queried.status == "CONFIRMED"

    cancelled = await container.cancel_order.execute(
        CancelOrderInput(
            order_id=placed.order_id,
            buyer_id="buyer-001",
            reason="改变购买计划",
        )
    )

    assert cancelled.status == "CANCELLED"
    assert sku.stock == initial_stock


def test_container_injects_configured_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ScriptedChatModel(responses=[])
    configured_reranker = object()
    monkeypatch.setattr(
        composition,
        "load_settings",
        lambda: build_composition_settings(
            reranker_base_url="https://reranker.example/v1",
        ),
    )
    monkeypatch.setattr(
        composition,
        "create_chat_model",
        lambda settings: model,
    )
    monkeypatch.setattr(
        composition,
        "build_category_knowledge_base",
        lambda settings: EmptyKnowledgeBase(),
    )
    monkeypatch.setattr(
        composition,
        "OpenAIEmbeddingClient",
        lambda settings: DeterministicEmbeddingClient(),
    )
    monkeypatch.setattr(
        composition,
        "QdrantProductIndex",
        lambda settings: RecordingProductVectorIndex(),
    )
    monkeypatch.setattr(
        composition,
        "HttpReranker",
        lambda settings: configured_reranker,
    )

    container = composition.build_container()

    assert (
        container.catalog_search._reranker
        is configured_reranker
    )


def test_container_shares_cached_embedder_when_redis_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EnabledCache:
        enabled = True

        async def close(self) -> None:
            return None

    model = ScriptedChatModel(responses=[])
    raw_embedder = DeterministicEmbeddingClient()
    cache = EnabledCache()
    monkeypatch.setattr(
        composition,
        "load_settings",
        lambda: build_composition_settings(
            redis_url="redis://localhost:6379/0",
        ),
    )
    monkeypatch.setattr(
        composition,
        "RedisCache",
        lambda redis_url: cache,
    )
    monkeypatch.setattr(
        composition,
        "create_chat_model",
        lambda settings: model,
    )
    monkeypatch.setattr(
        composition,
        "build_category_knowledge_base",
        lambda settings: EmptyKnowledgeBase(),
    )
    monkeypatch.setattr(
        composition,
        "OpenAIEmbeddingClient",
        lambda settings: raw_embedder,
    )
    monkeypatch.setattr(
        composition,
        "QdrantProductIndex",
        lambda settings: RecordingProductVectorIndex(),
    )

    container = composition.build_container()

    assert isinstance(
        container.embedder,
        CachedEmbeddingClient,
    )
    assert container.embedder._inner is raw_embedder
    assert container.embedder._cache is cache
    assert container.catalog_search._embedder is container.embedder
    assert (
        container.orchestrator._preference_selector._embedder
        is container.embedder
    )
    assert container.semantic_cache.enabled is True
    assert container.semantic_cache._cache is cache
    assert container.semantic_cache._embedder is container.embedder
    assert "chat=test-chat-model" in (
        container.semantic_cache._namespace
    )
    assert "embedding=test-embedding-model" in (
        container.semantic_cache._namespace
    )


def test_container_builds_queue_from_configured_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EnabledCache:
        enabled = True
        client = object()

        async def close(self) -> None:
            return None

    class RecordingQueue:
        def __init__(self, client) -> None:
            self.client = client

    model = ScriptedChatModel(responses=[])
    cache = EnabledCache()
    monkeypatch.setattr(
        composition,
        "load_settings",
        lambda: build_composition_settings(
            redis_url="redis://localhost:6379/0",
            queue_enabled=True,
        ),
    )
    monkeypatch.setattr(
        composition,
        "RedisCache",
        lambda redis_url: cache,
    )
    monkeypatch.setattr(
        composition,
        "RedisStreamTaskQueue",
        RecordingQueue,
    )
    monkeypatch.setattr(
        composition,
        "create_chat_model",
        lambda settings: model,
    )
    monkeypatch.setattr(
        composition,
        "build_category_knowledge_base",
        lambda settings: EmptyKnowledgeBase(),
    )
    monkeypatch.setattr(
        composition,
        "OpenAIEmbeddingClient",
        lambda settings: DeterministicEmbeddingClient(),
    )
    monkeypatch.setattr(
        composition,
        "QdrantProductIndex",
        lambda settings: RecordingProductVectorIndex(),
    )

    container = composition.build_container()

    assert isinstance(container.task_queue, RecordingQueue)
    assert container.task_queue.client is cache.client
    assert container.idempotency is not None
    assert container.idempotency._client is cache.client
    assert container.event_backplane is not None
