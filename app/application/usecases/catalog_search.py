from app.domain.catalog.ports.product_repository import (
    ProductRepository,
)
from app.domain.catalog.product import Product
from app.domain.catalog.product_search_spec import ProductSearchSpec


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
    ) -> None:
        self._product_repository = product_repository

    async def execute(
        self,
        spec: ProductSearchSpec,
    ) -> dict:
        products = await self._product_repository.list_all()
        query_terms = tokenize(spec.normalized_query)

        accepted: list[tuple[float, Product]] = []
        filtered_out: list[dict] = []

        for product in products:
            score = self._keyword_score(
                query_terms=query_terms,
                product=product,
                category=spec.category,
            )

            if score <= 0:
                continue

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

        accepted.sort(
            key=lambda item: item[0],
            reverse=True,
        )

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
            "recall_strategy": "keyword_2gram",
        }

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