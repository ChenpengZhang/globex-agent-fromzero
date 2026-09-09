import logging

from app.domain.catalog.ports.product_repository import (
    ProductRepository,
)
from app.domain.catalog.ports.retrieval_ports import (
    EmbeddingClient,
    ProductVectorIndex,
    Reranker,
)
from app.domain.catalog.product import Product
from app.domain.catalog.product_search_spec import ProductSearchSpec


logger = logging.getLogger(__name__)

_RECALL_TOP_N = 8


def tokenize(text: str) -> set[str]:
    """generate simple tokens from search text"""

    terms: set[str] = set()

    for chunk in text.lower().split():
        terms.add(chunk)

        contains_chinese = any(
            "\u4e00" <= character <= "\u9fff"
            for character in chunk
        )

        if contains_chinese and len(chunk) >= 2:
            terms.update(
                chunk[index : index + 2]
                for index in range(len(chunk) - 1)
            )

    return terms


class CatalogSearchUseCase:
    def __init__(
        self,
        product_repository: ProductRepository,
        embedder: EmbeddingClient | None = None,
        vector_index: ProductVectorIndex | None = None,
        reranker: Reranker | None = None,
        # Parameters can be set to None to ensure downgrading
    ) -> None:
        self._product_repository = product_repository
        self._embedder = embedder
        self._vector_index = vector_index
        self._reranker = reranker

    async def execute(
        self,
        spec: ProductSearchSpec,
    ) -> dict:
        rerank_applied = False
        scored: list[tuple[float, Product]] = []
        recall_strategy = "keyword_2gram"

        if (
            self._embedder is not None
            and self._vector_index is not None
        ):
            try:
                scored = await self._vector_recall(spec)

                if scored:
                    recall_strategy = "embedding_only"

            except Exception as error:
                logger.warning(
                    "向量召回不可用，降级关键词召回：%s",
                    error,
                )
                scored = []

        if not scored:
            scored = await self._keyword_recall(spec)
            recall_strategy = "keyword_2gram"
        if (
            recall_strategy == "embedding_only"
            and scored
            and self._reranker is not None
        ):
            try:
                scored = await self._rerank(
                    spec=spec,
                    scored=scored,
                )
                recall_strategy = "embedding_rerank"
                rerank_applied = True

            except Exception as error:
                logger.warning(
                    "Reranker 不可用，保留向量召回顺序：%s",
                    error,
                )

        accepted: list[tuple[float, Product]] = []
        filtered_out: list[dict] = []

        for score, product in scored:

            rejected_reason = self._rejected_reason(
                product=product,
                spec=spec,
            )

            if rejected_reason is not None:
                filtered_out.append(
                    self._to_filtered_product(
                        product=product,
                        reason=rejected_reason,
                    ),
                )
                continue

            accepted.append((score, product))

        hits = [
            self._to_product_card(
                product=product,
                score=score,
            )
            for score, product in accepted[: spec.top_k]
        ]

        return {
            "hits": hits,
            "filtered_out": filtered_out[:3],
            "total_candidates": len(accepted),
            "recall_strategy": recall_strategy,
            "rerank_applied": rerank_applied,
        }

    async def _vector_recall(
        self,
        spec: ProductSearchSpec,
    ) -> list[tuple[float, Product]]:
        if (
            self._embedder is None
            or self._vector_index is None
        ):
            raise RuntimeError(
                "向量检索基础设施未配置"
            )

        query_embedding = await self._embedder.embed(
            spec.normalized_query,
        )

        vector_hits = await self._vector_index.search(
            embedding=query_embedding,
            top_n=_RECALL_TOP_N,
        )

        products = await self._product_repository.find_by_ids(
            [
                hit.product_id
                for hit in vector_hits
            ]
        )

        products_by_id = {
            product.product_id: product
            for product in products
        }

        return [
            (
                hit.score,
                products_by_id[hit.product_id],
            )
            for hit in vector_hits
            if hit.product_id in products_by_id
        ]

    async def _rerank(
        self,
        spec: ProductSearchSpec,
        scored: list[tuple[float, Product]],
    ) -> list[tuple[float, Product]]:
        if self._reranker is None:
            raise RuntimeError(
                "Reranker 未配置"
            )

        documents = [
            product.searchable_text()
            for _, product in scored
        ]

        rerank_scores = await self._reranker.rerank(
            query=spec.normalized_query,
            documents=documents,
        )

        if len(rerank_scores) != len(scored):
            raise RuntimeError(
                "Reranker 返回的分数数量与候选数量不一致"
            )

        reranked = [
            (
                rerank_scores[index],
                product,
            )
            for index, (_, product) in enumerate(scored)
        ]

        reranked.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return reranked

    async def _keyword_recall(
        self,
        spec: ProductSearchSpec,
    ) -> list[tuple[float, Product]]:
        products = await self._product_repository.list_all()
        query_terms = tokenize(spec.normalized_query)

        candidates: list[tuple[float, Product]] = []

        for product in products:
            score = self._keyword_score(
                query_terms=query_terms,
                product=product,
                category=spec.category,
            )

            if score > 0:
                candidates.append(
                    (
                        score,
                        product,
                    )
                )

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return candidates

    @staticmethod
    def _keyword_score(
        query_terms: set[str],
        product: Product,
        category: str | None,
    ) -> float:
        product_terms = tokenize(
            product.searchable_text(),
        )

        matched_terms = query_terms & product_terms
        # In this simplest version, we just count the number of matched terms.
        if not matched_terms:
            return 0.0

        score = float(len(matched_terms))

        if category and category in product.category:
            score += 3.0 # If the term matches +3 points.

        return score

    @staticmethod
    def _rejected_reason(
        product: Product,
        spec: ProductSearchSpec,
    ) -> str | None:
        if (
            spec.ship_to is not None
            and spec.ship_to not in product.ships_to
        ):
            return "ship_to_unavailable"

        primary_price = product.primary_sku().price

        if primary_price.currency != spec.target_currency:
            return "currency_unsupported"

        if spec.price_max_major is not None:
            price_major = primary_price.to_major_units()

            if price_major > spec.price_max_major:
                return "over_price_cap"

        return None

    @staticmethod
    def _to_product_card(
        product: Product,
        score: float,
    ) -> dict:
        return {
            "product_id": product.product_id,
            "title": product.title,
            "brand": product.brand,
            "category": product.category,
            "origin_country": product.origin_country,
            "ships_to": product.ships_to,
            "skus": [
                {
                    "sku_id": sku.sku_id,
                    "spec": sku.spec,
                    "price_major": float(
                        sku.price.to_major_units(),
                    ),
                    "currency": sku.price.currency,
                    "stock": sku.stock,
                }
                for sku in product.skus
            ],
            "score": round(score, 4),
        }

    @staticmethod
    def _to_filtered_product(
        product: Product,
        reason: str,
    ) -> dict:
        primary_price = product.primary_sku().price

        return {
            "product_id": product.product_id,
            "title": product.title,
            "price_major": float(
                primary_price.to_major_units(),
            ),
            "currency": primary_price.currency,
            "reason": reason,
        }
