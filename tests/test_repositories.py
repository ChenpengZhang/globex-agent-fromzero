import pytest

from app.domain.catalog.money import Money
from app.domain.catalog.product import Product
from app.domain.catalog.sku import Sku
from app.domain.order.address import Address
from app.domain.order.order import Order
from app.domain.order.order_line import OrderLine
from app.infrastructure.persistence.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)


def make_product(product_id: str = "product-001") -> Product:
    return Product(
        product_id=product_id,
        title="轻便旅行背包",
        brand="Globex",
        category="旅行装备",
        origin_country="CN",
        description="适合短途旅行",
        ships_to=["CN", "US"],
        skus=[
            Sku(
                sku_id=f"{product_id}-black",
                spec="black",
                price=Money.from_major_units("199.90", "CNY"),
                stock=5,
            )
        ],
    )


def make_order(order_id: str = "GBX-000001") -> Order:
    return Order.place(
        order_id=order_id,
        buyer_id="buyer-001",
        shipping_address=Address(
            recipient_name="Alice",
            country="US",
            state="New York",
            city="New York City",
            address_line="123 Broadway",
            postal_code="10001",
            phone="+1 212 555 0100",
        ),
        lines=[
            OrderLine(
                product_id="product-001",
                sku_id="product-001-black",
                title="轻便旅行背包 - black",
                unit_price=Money.from_major_units("199.90", "CNY"),
                quantity=1,
            )
        ],
    )


@pytest.mark.asyncio
async def test_product_repository_finds_one_product_by_id() -> None:
    expected = make_product()
    repository = InMemoryProductRepository([expected])

    result = await repository.find_by_id("product-001")

    assert result is expected


@pytest.mark.asyncio
async def test_product_repository_returns_none_for_missing_id() -> None:
    repository = InMemoryProductRepository([make_product()])

    assert await repository.find_by_id("missing") is None


@pytest.mark.asyncio
async def test_order_repository_generates_sequential_ids() -> None:
    repository = InMemoryOrderRepository()

    assert await repository.next_order_id() == "GBX-000001"
    assert await repository.next_order_id() == "GBX-000002"


@pytest.mark.asyncio
async def test_order_repository_saves_and_finds_order() -> None:
    repository = InMemoryOrderRepository()
    expected = make_order()

    await repository.save(expected)

    assert await repository.find_by_id(expected.order_id) is expected
    assert await repository.find_by_id("missing") is None


@pytest.mark.asyncio
async def test_order_repository_save_replaces_same_order_id() -> None:
    repository = InMemoryOrderRepository()
    original = make_order()
    replacement = make_order()

    await repository.save(original)
    await repository.save(replacement)

    assert await repository.find_by_id(original.order_id) is replacement
