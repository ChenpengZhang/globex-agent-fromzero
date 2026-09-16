import pytest

from app.domain.catalog.ports.retrieval_ports import VectorHit
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import (
    build_seed_products,
)
from app.infrastructure.vector.index_bootstrap import (
    bootstrap_product_index,
    _generate_fingerprint,
)


class RecordingEmbedder:
    def __init__(
        self,
        *,
        vectors: list[list[float]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.vectors = vectors
        self.error = error
        self.batch_calls: list[list[str]] = []

    async def embed(self, text: str) -> list[float]:
        return [1.0]

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        self.batch_calls.append(list(texts))

        if self.error is not None:
            raise self.error

        if self.vectors is not None:
            return self.vectors

        return [[1.0, 0.0] for _ in texts]


class RecordingVectorIndex:
    def __init__(self) -> None:
        self.ready_dimensions: list[int] = []
        self.upsert_calls: list[dict] = []
        self.fingerprints: dict[str, str] = {}

    async def get_fingerprints_dict(self, product_ids):
        return {
            key: value for key, value in self.fingerprints.items()
            if key in product_ids
        }

    async def ensure_ready(self, vector_dim: int) -> None:
        self.ready_dimensions.append(vector_dim)

    async def upsert_products(
        self,
        products,
        embeddings: list[list[float]],
        fingerprints: list[str],
    ) -> None:
        self.upsert_calls.append(
            {
                "products": list(products),
                "embeddings": list(embeddings),
            }
        )
        self.fingerprints.update(
            (product.product_id, fingerprint)
            for product, fingerprint in zip(products, fingerprints)
        )

    async def search(
        self,
        embedding: list[float],
        top_n: int,
    ) -> list[VectorHit]:
        return []


@pytest.mark.asyncio
async def test_bootstrap_embeds_searchable_text_and_upserts_products(
) -> None:
    products = build_seed_products()[:2]
    repository = InMemoryProductRepository(products)
    embedder = RecordingEmbedder()
    index = RecordingVectorIndex()

    result = await bootstrap_product_index(
        product_repository=repository,
        embedder=embedder,  # type: ignore[arg-type]
        vector_index=index,  # type: ignore[arg-type]
        embedder_namespace="test-model-v1",
    )

    assert result is True
    assert embedder.batch_calls == [
        [product.searchable_text() for product in products]
    ]
    assert index.ready_dimensions == [2]
    assert index.upsert_calls == [
        {
            "products": products,
            "embeddings": [
                [1.0, 0.0],
                [1.0, 0.0],
            ],
        }
    ]


@pytest.mark.asyncio
async def test_bootstrap_skips_empty_product_repository() -> None:
    repository = InMemoryProductRepository([])
    embedder = RecordingEmbedder()
    index = RecordingVectorIndex()

    result = await bootstrap_product_index(
        product_repository=repository,
        embedder=embedder,  # type: ignore[arg-type]
        vector_index=index,  # type: ignore[arg-type]
        embedder_namespace="test-model-v1",
    )

    assert result is False
    assert embedder.batch_calls == []
    assert index.ready_dimensions == []
    assert index.upsert_calls == []


@pytest.mark.asyncio
async def test_bootstrap_skips_unchanged_products() -> None:
    products = build_seed_products()[:2]
    repository = InMemoryProductRepository(products)
    embedder = RecordingEmbedder()
    index = RecordingVectorIndex()
    assert await bootstrap_product_index(repository, embedder, index, "v1")
    assert index.fingerprints == {
        product.product_id: _generate_fingerprint(product.searchable_text(), "v1")
        for product in products
    }
    embedder.batch_calls.clear()
    index.upsert_calls.clear()
    index.ready_dimensions.clear()

    assert await bootstrap_product_index(repository, embedder, index, "v1")
    assert embedder.batch_calls == []
    assert index.upsert_calls == []
    assert index.ready_dimensions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["text", "namespace", "missing", "wrong_product"])
async def test_bootstrap_updates_only_stale_products(change) -> None:
    products = build_seed_products()[:2]
    repository = InMemoryProductRepository(products)
    embedder = RecordingEmbedder()
    index = RecordingVectorIndex()
    assert await bootstrap_product_index(repository, embedder, index, "v1")
    embedder.batch_calls.clear()
    index.upsert_calls.clear()
    namespace = "v1"
    expected = products[:1]

    if change == "text":
        products[0].description += " waterproof"
    elif change == "namespace":
        namespace = "v2"
        expected = products
    elif change == "missing":
        del index.fingerprints[products[0].product_id]
    else:
        # Another product's matching fingerprint must not count as a hit.
        index.fingerprints[products[1].product_id] = index.fingerprints.pop(products[0].product_id)
        expected = products

    assert await bootstrap_product_index(repository, embedder, index, namespace)
    assert embedder.batch_calls == [[p.searchable_text() for p in expected]]
    assert len(index.upsert_calls) == 1
    assert index.upsert_calls[0]["products"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("vectors", [[[1.0]], [[], []], [[1.0], [1.0, 0.0]]])
async def test_bootstrap_rejects_invalid_vectors(vectors) -> None:
    repository = InMemoryProductRepository(build_seed_products()[:2])
    index = RecordingVectorIndex()
    assert not await bootstrap_product_index(
        repository, RecordingEmbedder(vectors=vectors), index, "v1"
    )
    assert index.ready_dimensions == []
    assert index.upsert_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "embedder",
    [
        RecordingEmbedder(vectors=[]),
        RecordingEmbedder(
            error=RuntimeError("embedding service unavailable"),
        ),
    ],
)
async def test_bootstrap_degrades_when_embedding_is_unavailable(
    embedder: RecordingEmbedder,
) -> None:
    repository = InMemoryProductRepository(
        build_seed_products()[:1]
    )
    index = RecordingVectorIndex()

    result = await bootstrap_product_index(
        product_repository=repository,
        embedder=embedder,  # type: ignore[arg-type]
        vector_index=index,  # type: ignore[arg-type]
        embedder_namespace="test-model-v1",
    )

    assert result is False
    assert index.ready_dimensions == []
    assert index.upsert_calls == []
