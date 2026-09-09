from types import SimpleNamespace

import pytest

from app.application.usecases.catalog_search import (
    CatalogSearchUseCase,
)
from app.domain.catalog.product_search_spec import ProductSearchSpec
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import (
    build_seed_products,
)
from app.infrastructure.vector.index_bootstrap import (
    bootstrap_product_index,
)
from app.infrastructure.vector.qdrant_product_index import (
    QdrantProductIndex,
)


_TERMS = (
    "登机箱",
    "折叠",
    "三件套",
    "轻便",
)


class AxisEmbeddingClient:
    """Deterministic semantic axes for an offline full pipeline."""

    def __init__(self) -> None:
        self.single_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    @staticmethod
    def _vector(text: str) -> list[float]:
        return [
            1.0 if term in text else 0.0
            for term in _TERMS
        ]

    async def embed(self, text: str) -> list[float]:
        self.single_calls.append(text)
        return self._vector(text)

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        return [self._vector(text) for text in texts]


class FoldingBagReranker:
    def __init__(self) -> None:
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
        return [
            0.99 if "折叠" in document else 0.20
            for document in documents
        ]


@pytest.mark.asyncio
async def test_product_retrieval_pipeline_from_indexing_to_cards(
    tmp_path,
) -> None:
    products = build_seed_products()
    repository = InMemoryProductRepository(products)
    embedder = AxisEmbeddingClient()
    reranker = FoldingBagReranker()
    settings = SimpleNamespace(
        qdrant_url="",
        data_dir=tmp_path,
        product_vector_collection="integration_products",
    )
    index = QdrantProductIndex(
        settings,  # type: ignore[arg-type]
    )

    try:
        bootstrapped = await bootstrap_product_index(
            product_repository=repository,
            embedder=embedder,  # type: ignore[arg-type]
            vector_index=index,
        )
        usecase = CatalogSearchUseCase(
            product_repository=repository,
            embedder=embedder,  # type: ignore[arg-type]
            vector_index=index,
            reranker=reranker,  # type: ignore[arg-type]
        )

        result = await usecase.execute(
            ProductSearchSpec(
                normalized_query="折叠 轻便",
                ship_to="CN",
                price_max_major=300,
            )
        )

        assert bootstrapped is True
        assert embedder.batch_calls == [
            [product.searchable_text() for product in products]
        ]
        assert embedder.single_calls == ["折叠 轻便"]
        assert len(reranker.calls) == 1
        assert reranker.calls[0]["query"] == "折叠 轻便"
        assert [
            hit["product_id"]
            for hit in result["hits"]
        ] == ["P1003", "P1001"]
        assert result["filtered_out"] == [
            {
                "product_id": "P1002",
                "title": "TrailOx 20寸登机箱",
                "price_major": 899.0,
                "currency": "CNY",
                "reason": "over_price_cap",
            }
        ]
        assert result["recall_strategy"] == (
            "embedding_rerank"
        )
        assert result["rerank_applied"] is True
    finally:
        await index.close()
