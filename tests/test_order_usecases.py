import pytest

from app.application.dto.order import CancelOrderInput, QueryOrderInput
from app.application.usecases.cancel_order import CancelOrderUseCase
from app.application.usecases.order_access import (
    OrderAccessDeniedError,
    OrderNotFoundError,
)
from app.application.usecases.query_order import QueryOrderUseCase
from app.domain.catalog.money import Money
from app.domain.catalog.product import Product
from app.domain.catalog.sku import Sku
from app.domain.order.address import Address
from app.domain.order.order import Order, OrderStatus
from app.domain.order.order_line import OrderLine
from app.infrastructure.persistence.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)


def make_address() -> Address:
    return Address(
        recipient_name="Alice",
        country="US",
        state="New York",
        city="New York City",
        address_line="123 Broadway",
        postal_code="10001",
        phone="+1 212 555 0100",
    )


def make_product(
    *,
    sku_id: str = "sku-black",
    stock: int = 3,
) -> tuple[Product, Sku]:
    sku = Sku(
        sku_id=sku_id,
        spec="black",
        price=Money.from_major_units("199.90", "CNY"),
        stock=stock,
    )
    return (
        Product(
            product_id="product-001",
            title="轻便旅行背包",
            brand="Globex",
            category="旅行装备",
            origin_country="CN",
            description="适合短途旅行",
            ships_to=["US", "CN"],
            skus=[sku],
        ),
        sku,
    )


def make_order(
    *,
    sku_id: str = "sku-black",
    confirmed: bool = True,
) -> Order:
    values = {
        "order_id": "GBX-000001",
        "buyer_id": "buyer-001",
        "shipping_address": make_address(),
        "lines": [
            OrderLine(
                product_id="product-001",
                sku_id=sku_id,
                title="轻便旅行背包 (black)",
                unit_price=Money.from_major_units("199.90", "CNY"),
                quantity=2,
            )
        ],
    }
    if confirmed:
        return Order.place(**values)
    return Order(**values)


async def save_order(
    repository: InMemoryOrderRepository,
    order: Order,
) -> None:
    await repository.save(order)


@pytest.mark.asyncio
async def test_query_order_returns_owned_order_output() -> None:
    repository = InMemoryOrderRepository()
    await save_order(repository, make_order())
    use_case = QueryOrderUseCase(repository)

    output = await use_case.execute(
        QueryOrderInput(
            order_id="GBX-000001",
            buyer_id="buyer-001",
        )
    )

    assert output.order_id == "GBX-000001"
    assert output.status == "CONFIRMED"
    assert output.total_amount.amount_major == "399.80"


@pytest.mark.asyncio
async def test_query_order_rejects_missing_order() -> None:
    use_case = QueryOrderUseCase(InMemoryOrderRepository())

    with pytest.raises(OrderNotFoundError, match="订单不存在"):
        await use_case.execute(
            QueryOrderInput("GBX-999999", "buyer-001")
        )


@pytest.mark.asyncio
async def test_query_order_rejects_other_buyer() -> None:
    repository = InMemoryOrderRepository()
    await save_order(repository, make_order())
    use_case = QueryOrderUseCase(repository)

    with pytest.raises(OrderAccessDeniedError, match="无权访问"):
        await use_case.execute(
            QueryOrderInput("GBX-000001", "buyer-002")
        )


@pytest.mark.asyncio
async def test_cancel_order_restores_inventory_and_saves_state() -> None:
    product, sku = make_product(stock=3)
    order_repository = InMemoryOrderRepository()
    await save_order(order_repository, make_order())
    use_case = CancelOrderUseCase(
        InMemoryProductRepository([product]),
        order_repository,
    )

    output = await use_case.execute(
        CancelOrderInput(
            order_id="GBX-000001",
            buyer_id="buyer-001",
            reason="改变购买计划",
        )
    )

    stored = await order_repository.find_by_id("GBX-000001")
    assert sku.stock == 5
    assert stored is not None
    assert stored.status is OrderStatus.CANCELLED
    assert output.status == "CANCELLED"
    assert output.cancel_reason == "改变购买计划"


@pytest.mark.asyncio
async def test_cancel_order_cannot_restore_inventory_twice() -> None:
    product, sku = make_product(stock=3)
    order_repository = InMemoryOrderRepository()
    await save_order(order_repository, make_order())
    use_case = CancelOrderUseCase(
        InMemoryProductRepository([product]),
        order_repository,
    )
    command = CancelOrderInput(
        "GBX-000001",
        "buyer-001",
        "改变购买计划",
    )

    await use_case.execute(command)
    with pytest.raises(ValueError, match="只有已确认订单"):
        await use_case.execute(command)

    assert sku.stock == 5


@pytest.mark.asyncio
async def test_cancel_order_rejects_other_buyer_without_mutation() -> None:
    product, sku = make_product(stock=3)
    order = make_order()
    order_repository = InMemoryOrderRepository()
    await save_order(order_repository, order)
    use_case = CancelOrderUseCase(
        InMemoryProductRepository([product]),
        order_repository,
    )

    with pytest.raises(OrderAccessDeniedError, match="无权访问"):
        await use_case.execute(
            CancelOrderInput(
                "GBX-000001",
                "buyer-002",
                "改变购买计划",
            )
        )

    assert order.status is OrderStatus.CONFIRMED
    assert sku.stock == 3


@pytest.mark.asyncio
async def test_cancel_order_requires_existing_product_before_mutation() -> None:
    order = make_order()
    order_repository = InMemoryOrderRepository()
    await save_order(order_repository, order)
    use_case = CancelOrderUseCase(
        InMemoryProductRepository(),
        order_repository,
    )

    with pytest.raises(ValueError, match="商品不存在"):
        await use_case.execute(
            CancelOrderInput(
                "GBX-000001",
                "buyer-001",
                "改变购买计划",
            )
        )

    assert order.status is OrderStatus.CONFIRMED


@pytest.mark.asyncio
async def test_cancel_order_requires_existing_sku_before_mutation() -> None:
    product, available_sku = make_product(
        sku_id="another-sku",
        stock=3,
    )
    order = make_order(sku_id="missing-sku")
    order_repository = InMemoryOrderRepository()
    await save_order(order_repository, order)
    use_case = CancelOrderUseCase(
        InMemoryProductRepository([product]),
        order_repository,
    )

    with pytest.raises(ValueError, match="SKU 不存在"):
        await use_case.execute(
            CancelOrderInput(
                "GBX-000001",
                "buyer-001",
                "改变购买计划",
            )
        )

    assert order.status is OrderStatus.CONFIRMED
    assert available_sku.stock == 3


@pytest.mark.asyncio
async def test_cancel_order_rejects_draft_without_restoring_inventory() -> None:
    product, sku = make_product(stock=3)
    order = make_order(confirmed=False)
    order_repository = InMemoryOrderRepository()
    await save_order(order_repository, order)
    use_case = CancelOrderUseCase(
        InMemoryProductRepository([product]),
        order_repository,
    )

    with pytest.raises(ValueError, match="只有已确认订单"):
        await use_case.execute(
            CancelOrderInput(
                "GBX-000001",
                "buyer-001",
                "改变购买计划",
            )
        )

    assert order.status is OrderStatus.DRAFT
    assert sku.stock == 3
