from decimal import Decimal

import pytest

from app.domain.catalog.product_search_spec import ProductSearchSpec


def test_search_spec_normalizes_values() -> None:
    spec = ProductSearchSpec(
        normalized_query="  旅行装备 轻便  ",
        category=" 旅行装备 ",
        ship_to="cn",
        top_k=3,
        price_max_major="300.50",
        target_currency="cny",
    )

    assert spec.normalized_query == "旅行装备 轻便"
    assert spec.category == "旅行装备"
    assert spec.ship_to == "CN"
    assert spec.top_k == 3
    assert spec.price_max_major == Decimal("300.50")
    assert spec.target_currency == "CNY"


@pytest.mark.parametrize(
    "values",
    [
        {"normalized_query": ""},
        {"normalized_query": "旅行装备", "top_k": 0},
        {"normalized_query": "旅行装备", "top_k": 21},
        {"normalized_query": "旅行装备", "ship_to": "CHINA"},
        {
            "normalized_query": "旅行装备",
            "price_max_major": -1,
        },
        {
            "normalized_query": "旅行装备",
            "price_max_major": "not-a-number",
        },
    ],
)
def test_search_spec_rejects_invalid_values(
    values: dict,
) -> None:
    with pytest.raises(ValueError):
        ProductSearchSpec(**values)