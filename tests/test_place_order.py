import asyncio

import pytest

from app.application.dto.order import OrderItemInput, PlaceOrderInput
from app.application.usecases.place_order import PlaceOrderUseCase
from app.domain.catalog.money import Money
from app.domain.catalog.product import Product
from app.domain.catalog.sku import Sku
from app.domain.order.address import Address
from app.domain.order.order import Order
from app.infrastructure.persistence.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)


def make_address(country: str = "US") -> Address:
    return Address(
        recipient_name="Alice",
        country=country,
        state="New York",
        city="New York City",
        address_line="123 Broadway",
        postal_code="10001",
        phone="+1 212 555 0100",
    )


def make_product(
    *,
    product_id: str,
    sku_id: str,
    stock: int,
    amount_major: str = "199.90",
    ships_to: list[str] | None = None,
) -> tuple[Product, Sku]:
    sku = Sku(
        sku_id=sku_id,
        spec="black",
        price=Money.from_major_units(amount_major, "CNY"),
        stock=stock,
    )
    product = Product(
        product_id=product_id,
        title=f"商品 {product_id}",
        brand="Globex",
        category="旅行装备",
        origin_country="CN",
        description="测试商品",
        ships_to=ships_to or ["US", "CN"],
        skus=[sku],
    )
    return product, sku


def make_command(
    items: list[OrderItemInput],
    *,
    country: str = "US",
) -> PlaceOrderInput:
    return PlaceOrderInput(
        buyer_id="buyer-001",
        items=items,
        shipping_address=make_address(country),
    )


class FailingSaveOrderRepository(InMemoryOrderRepository):
    async def save(self, order: Order) -> None:
        raise RuntimeError("storage unavailable")


class CancelledIdOrderRepository(InMemoryOrderRepository):
    async def next_order_id(self) -> str:
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_place_order_deducts_inventory_and_saves_confirmed_order() -> None:
    product, sku = make_product(
        product_id="product-001",
        sku_id="sku-black",
        stock=5,
    )
    product_repository = InMemoryProductRepository([product])
    order_repository = InMemoryOrderRepository()
    use_case = PlaceOrderUseCase(product_repository, order_repository)

    output = await use_case.execute(
        make_command(
            [
                OrderItemInput(
                    product_id="product-001",
                    sku_id="sku-black",
                    quantity=2,
                )
            ]
        )
    )

    stored = await order_repository.find_by_id("GBX-000001")
    assert sku.stock == 3
    assert stored is not None
    assert stored.status.value == "CONFIRMED"
    assert output.order_id == "GBX-000001"
    assert output.status == "CONFIRMED"
    assert output.lines[0].title == "商品 product-001 (black)"
    assert output.total_amount.amount_major == "399.80"


@pytest.mark.asyncio
async def test_place_order_keeps_checkout_price_snapshot() -> None:
    product, sku = make_product(
        product_id="product-001",
        sku_id="sku-black",
        stock=5,
    )
    order_repository = InMemoryOrderRepository()
    use_case = PlaceOrderUseCase(
        InMemoryProductRepository([product]),
        order_repository,
    )

    await use_case.execute(
        make_command(
            [OrderItemInput("product-001", "sku-black", 1)]
        )
    )
    sku.price = Money.from_major_units("299.90", "CNY")

    stored = await order_repository.find_by_id("GBX-000001")
    assert stored is not None
    assert stored.lines[0].unit_price == Money.from_major_units(
        "199.90",
        "CNY",
    )


@pytest.mark.asyncio
async def test_place_order_rejects_missing_product() -> None:
    order_repository = InMemoryOrderRepository()
    use_case = PlaceOrderUseCase(
        InMemoryProductRepository(),
        order_repository,
    )

    with pytest.raises(ValueError, match="商品不存在"):
        await use_case.execute(
            make_command(
                [OrderItemInput("missing", "sku-black", 1)]
            )
        )

    assert await order_repository.find_by_id("GBX-000001") is None


@pytest.mark.asyncio
async def test_place_order_rejects_unsupported_destination_without_deduction() -> None:
    product, sku = make_product(
        product_id="product-001",
        sku_id="sku-black",
        stock=5,
        ships_to=["CN"],
    )
    use_case = PlaceOrderUseCase(
        InMemoryProductRepository([product]),
        InMemoryOrderRepository(),
    )

    with pytest.raises(ValueError, match="无法配送"):
        await use_case.execute(
            make_command(
                [OrderItemInput("product-001", "sku-black", 1)]
            )
        )

    assert sku.stock == 5


@pytest.mark.asyncio
async def test_place_order_rejects_missing_sku_without_deduction() -> None:
    product, sku = make_product(
        product_id="product-001",
        sku_id="sku-black",
        stock=5,
    )
    use_case = PlaceOrderUseCase(
        InMemoryProductRepository([product]),
        InMemoryOrderRepository(),
    )

    with pytest.raises(ValueError, match="SKU 不存在"):
        await use_case.execute(
            make_command(
                [OrderItemInput("product-001", "missing", 1)]
            )
        )

    assert sku.stock == 5


@pytest.mark.asyncio
async def test_place_order_restores_prior_deductions_after_later_failure() -> None:
    first_product, first_sku = make_product(
        product_id="product-001",
        sku_id="sku-first",
        stock=5,
    )
    second_product, second_sku = make_product(
        product_id="product-002",
        sku_id="sku-second",
        stock=1,
    )
    use_case = PlaceOrderUseCase(
        InMemoryProductRepository([first_product, second_product]),
        InMemoryOrderRepository(),
    )

    with pytest.raises(ValueError, match="库存不足"):
        await use_case.execute(
            make_command(
                [
                    OrderItemInput("product-001", "sku-first", 2),
                    OrderItemInput("product-002", "sku-second", 2),
                ]
            )
        )

    assert first_sku.stock == 5
    assert second_sku.stock == 1


@pytest.mark.asyncio
async def test_place_order_restores_inventory_when_save_fails() -> None:
    product, sku = make_product(
        product_id="product-001",
        sku_id="sku-black",
        stock=5,
    )
    use_case = PlaceOrderUseCase(
        InMemoryProductRepository([product]),
        FailingSaveOrderRepository(),
    )

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await use_case.execute(
            make_command(
                [OrderItemInput("product-001", "sku-black", 2)]
            )
        )

    assert sku.stock == 5


@pytest.mark.asyncio
async def test_place_order_restores_inventory_when_task_is_cancelled() -> None:
    product, sku = make_product(
        product_id="product-001",
        sku_id="sku-black",
        stock=5,
    )
    use_case = PlaceOrderUseCase(
        InMemoryProductRepository([product]),
        CancelledIdOrderRepository(),
    )

    with pytest.raises(asyncio.CancelledError):
        await use_case.execute(
            make_command(
                [OrderItemInput("product-001", "sku-black", 2)]
            )
        )

    assert sku.stock == 5
