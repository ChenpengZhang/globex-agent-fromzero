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

    async def ensure_ready(self, vector_dim: int) -> None:
        self.ready_dimensions.append(vector_dim)

    async def upsert_products(
        self,
        products,
        embeddings: list[list[float]],
    ) -> None:
        self.upsert_calls.append(
            {
                "products": list(products),
                "embeddings": list(embeddings),
            }
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
    )

    assert result is False
    assert embedder.batch_calls == []
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
    )

    assert result is False
    assert index.ready_dimensions == []
    assert index.upsert_calls == []
