from app.domain.catalog.money import Money
from app.domain.catalog.product import Product
from app.domain.catalog.sku import Sku


def make_product() -> tuple[Product, Sku, Sku]:
    black = Sku(
        sku_id="sku-black",
        spec="black",
        price=Money.from_major_units("199.90", "CNY"),
        stock=5,
    )
    blue = Sku(
        sku_id="sku-blue",
        spec="blue",
        price=Money.from_major_units("209.90", "CNY"),
        stock=3,
    )
    product = Product(
        product_id="product-001",
        title="轻便旅行背包",
        brand="Globex",
        category="旅行装备",
        origin_country="CN",
        description="适合短途旅行",
        ships_to=["CN", "US"],
        skus=[black, blue],
    )
    return product, black, blue


def test_find_sku_returns_matching_entity_from_product() -> None:
    product, _, blue = make_product()

    result = product.find_sku(" sku-blue ")

    assert result is blue


def test_find_sku_returns_none_when_sku_is_missing() -> None:
    product, _, _ = make_product()

    assert product.find_sku("sku-missing") is None


def test_find_sku_returns_none_for_blank_identifier() -> None:
    product, _, _ = make_product()

    assert product.find_sku("   ") is None
