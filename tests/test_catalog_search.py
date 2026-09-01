import pytest

from app.application.usecases.catalog_search import (
    CatalogSearchUseCase,
)
from app.domain.catalog.money import Money
from app.domain.catalog.product import Product
from app.domain.catalog.product_search_spec import ProductSearchSpec
from app.domain.catalog.sku import Sku
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import (
    build_seed_products,
)


def build_usecase() -> CatalogSearchUseCase:
    repository = InMemoryProductRepository(
        build_seed_products(),
    )
    return CatalogSearchUseCase(repository)


def build_product(
    product_id: str,
    title: str,
    category: str,
) -> Product:
    return Product(
        product_id=product_id,
        title=title,
        brand="TestBrand",
        category=category,
        origin_country="CN",
        description="轻便旅行用品",
        ships_to=["CN"],
        skus=[
            Sku(
                sku_id=f"{product_id}-S1",
                spec="标准款",
                price=Money.from_major_units(
                    100,
                    "CNY",
                ),
                stock=10,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_keyword_search_returns_ranked_products() -> None:
    usecase = build_usecase()

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="旅行 轻便",
        ),
    )

    product_ids = [
        hit["product_id"]
        for hit in result["hits"]
    ]

    assert product_ids == [
        "P1001",
        "P1003",
        "P1002",
    ]
    assert result["recall_strategy"] == "keyword_2gram"
    assert result["total_candidates"] == 3


@pytest.mark.asyncio
async def test_category_match_increases_ranking_score() -> None:
    other_category = build_product(
        product_id="P2001",
        title="轻便旅行收纳用品",
        category="家居生活",
    )
    matching_category = build_product(
        product_id="P2002",
        title="轻便旅行背包",
        category="旅行装备",
    )

    repository = InMemoryProductRepository(
        [
            other_category,
            matching_category,
        ],
    )
    usecase = CatalogSearchUseCase(repository)

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="轻便 旅行",
            category="旅行装备",
        ),
    )

    assert result["hits"][0]["product_id"] == "P2002"
    assert (
        result["hits"][0]["score"]
        > result["hits"][1]["score"]
    )


@pytest.mark.asyncio
async def test_price_cap_filters_expensive_products() -> None:
    usecase = build_usecase()

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="旅行",
            price_max_major=300,
        ),
    )

    hit_ids = {
        hit["product_id"]
        for hit in result["hits"]
    }

    assert hit_ids == {"P1001", "P1003"}

    assert result["filtered_out"] == [
        {
            "product_id": "P1002",
            "title": "TrailOx 20寸登机箱",
            "price_major": 899.0,
            "currency": "CNY",
            "reason": "over_price_cap",
        },
    ]


@pytest.mark.asyncio
async def test_ship_to_filters_unavailable_products() -> None:
    usecase = build_usecase()

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="旅行",
            ship_to="US",
        ),
    )

    hit_ids = {
        hit["product_id"]
        for hit in result["hits"]
    }

    assert hit_ids == {"P1001", "P1002"}

    filtered_reasons = {
        item["product_id"]: item["reason"]
        for item in result["filtered_out"]
    }

    assert filtered_reasons == {
        "P1003": "ship_to_unavailable",
    }


@pytest.mark.asyncio
async def test_top_k_limits_hits_not_total_candidates() -> None:
    usecase = build_usecase()

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="旅行",
            top_k=1,
        ),
    )

    assert len(result["hits"]) == 1
    assert result["hits"][0]["product_id"] == "P1001"
    assert result["total_candidates"] == 3


@pytest.mark.asyncio
async def test_unknown_query_returns_empty_result() -> None:
    usecase = build_usecase()

    result = await usecase.execute(
        ProductSearchSpec(
            normalized_query="完全不存在的关键词",
        ),
    )

    assert result["hits"] == []
    assert result["filtered_out"] == []
    assert result["total_candidates"] == 0