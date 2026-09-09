import pytest

from app.application.usecases.catalog_search import (
    CatalogSearchUseCase,
)
from app.domain.catalog.ports.retrieval_ports import VectorHit
from app.domain.catalog.product_search_spec import ProductSearchSpec
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import (
    build_seed_products,
)


class RecordingEmbedder:
    def __init__(
        self,
        *,
        vector: list[float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.vector = vector or [0.75, 0.25]
        self.error = error
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)

        if self.error is not None:
            raise self.error

        return self.vector

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return [self.vector for _ in texts]


class RecordingVectorIndex:
    def __init__(
        self,
        *,
        hits: list[VectorHit] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.hits = hits or []
        self.error = error
        self.search_calls: list[dict] = []

    async def ensure_ready(self, vector_dim: int) -> None:
        return None

    async def upsert_products(
        self,
        products,
        embeddings: list[list[float]],
    ) -> None:
        return None

    async def search(
        self,
        embedding: list[float],
        top_n: int,
    ) -> list[VectorHit]:
        self.search_calls.append(
            {
                "embedding": embedding,
                "top_n": top_n,
            }
        )

        if self.error is not None:
            raise self.error

        return self.hits


class RecordingReranker:
    def __init__(
        self,
        *,
        scores: list[float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.scores = scores or []
        self.error = error
        self.calls: list[dict] = []

    async def rerank(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        self.calls.append(
            {
                "query": query,
                "documents": list(documents),
            }
        )

        if self.error is not None:
            raise self.error

        return self.scores


def build_usecase(
    embedder: RecordingEmbedder | None,
    vector_index: RecordingVectorIndex | None,
    reranker: RecordingReranker | None = None,
) -> CatalogSearchUseCase:
    return CatalogSearchUseCase(
        product_repository=InMemoryProductRepository(
            build_seed_products()
        ),
        embedder=embedder,  # type: ignore[arg-type]
        vector_index=vector_index,  # type: ignore[arg-type]
        reranker=reranker,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_vector_recall_preserves_hit_order_and_scores() -> None:
    embedder = RecordingEmbedder(vector=[0.6, 0.4])
    index = RecordingVectorIndex(
        hits=[
            VectorHit(product_id="P1003", score=0.91),
            VectorHit(product_id="P1001", score=0.82),
        ]
    )
    usecase = build_usecase(embedder, index)

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="可折叠的轻便通勤包",
        )
    )

    assert embedder.calls == ["可折叠的轻便通勤包"]
    assert index.search_calls == [
        {
            "embedding": [0.6, 0.4],
            "top_n": 8,
        }
    ]
    assert [
        hit["product_id"]
        for hit in result["hits"]
    ] == ["P1003", "P1001"]
    assert [hit["score"] for hit in result["hits"]] == [
        0.91,
        0.82,
    ]
    assert result["recall_strategy"] == "embedding_only"
    assert result["rerank_applied"] is False


@pytest.mark.asyncio
async def test_hard_filters_run_after_vector_recall() -> None:
    embedder = RecordingEmbedder()
    index = RecordingVectorIndex(
        hits=[
            VectorHit(product_id="P1002", score=0.99),
            VectorHit(product_id="P1001", score=0.75),
        ]
    )
    usecase = build_usecase(embedder, index)

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="旅行装备",
            ship_to="CN",
            price_max_major=300,
        )
    )

    assert [
        hit["product_id"]
        for hit in result["hits"]
    ] == ["P1001"]
    assert result["filtered_out"] == [
        {
            "product_id": "P1002",
            "title": "TrailOx 20寸登机箱",
            "price_major": 899.0,
            "currency": "CNY",
            "reason": "over_price_cap",
        }
    ]
    assert result["recall_strategy"] == "embedding_only"


@pytest.mark.asyncio
async def test_reranker_changes_vector_candidate_order() -> None:
    products = build_seed_products()
    embedder = RecordingEmbedder()
    index = RecordingVectorIndex(
        hits=[
            VectorHit(product_id="P1001", score=0.98),
            VectorHit(product_id="P1003", score=0.81),
        ]
    )
    reranker = RecordingReranker(scores=[0.15, 0.96])
    usecase = build_usecase(embedder, index, reranker)

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="可折叠的轻便双肩包",
        )
    )

    assert reranker.calls == [
        {
            "query": "可折叠的轻便双肩包",
            "documents": [
                products[0].searchable_text(),
                products[2].searchable_text(),
            ],
        }
    ]
    assert [
        hit["product_id"]
        for hit in result["hits"]
    ] == ["P1003", "P1001"]
    assert [hit["score"] for hit in result["hits"]] == [
        0.96,
        0.15,
    ]
    assert result["recall_strategy"] == "embedding_rerank"
    assert result["rerank_applied"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reranker",
    [
        RecordingReranker(
            error=RuntimeError("reranker unavailable"),
        ),
        RecordingReranker(scores=[0.5]),
    ],
)
async def test_reranker_failure_preserves_vector_order(
    reranker: RecordingReranker,
) -> None:
    embedder = RecordingEmbedder()
    index = RecordingVectorIndex(
        hits=[
            VectorHit(product_id="P1001", score=0.98),
            VectorHit(product_id="P1003", score=0.81),
        ]
    )
    usecase = build_usecase(embedder, index, reranker)

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="轻便旅行装备",
        )
    )

    assert [
        hit["product_id"]
        for hit in result["hits"]
    ] == ["P1001", "P1003"]
    assert [hit["score"] for hit in result["hits"]] == [
        0.98,
        0.81,
    ]
    assert result["recall_strategy"] == "embedding_only"
    assert result["rerank_applied"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("embedder", "index"),
    [
        (
            RecordingEmbedder(
                error=RuntimeError("embedding unavailable")
            ),
            RecordingVectorIndex(),
        ),
        (
            RecordingEmbedder(),
            RecordingVectorIndex(
                error=RuntimeError("qdrant unavailable")
            ),
        ),
        (
            RecordingEmbedder(),
            RecordingVectorIndex(hits=[]),
        ),
        (
            RecordingEmbedder(),
            RecordingVectorIndex(
                hits=[
                    VectorHit(
                        product_id="deleted-product",
                        score=0.99,
                    )
                ]
            ),
        ),
    ],
)
async def test_vector_recall_degrades_to_keyword(
    embedder: RecordingEmbedder,
    index: RecordingVectorIndex,
) -> None:
    usecase = build_usecase(embedder, index)

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="旅行 轻便",
        )
    )

    assert result["recall_strategy"] == "keyword_2gram"
    assert [
        hit["product_id"]
        for hit in result["hits"]
    ] == ["P1001", "P1003", "P1002"]


@pytest.mark.asyncio
async def test_incomplete_vector_configuration_uses_keyword_without_api_call(
) -> None:
    embedder = RecordingEmbedder()
    usecase = build_usecase(
        embedder=embedder,
        vector_index=None,
    )

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="旅行 轻便",
        )
    )

    assert result["recall_strategy"] == "keyword_2gram"
    assert embedder.calls == []
