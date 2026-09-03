import pytest

import app.composition as composition
from app.application.dto.order import (
    CancelOrderInput,
    OrderItemInput,
    PlaceOrderInput,
    QueryOrderInput,
)
from app.domain.order.address import Address
from tests.fakes import ScriptedChatModel


@pytest.mark.asyncio
async def test_container_shares_repositories_across_order_use_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ScriptedChatModel(responses=[])
    monkeypatch.setattr(
        composition,
        "load_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        composition,
        "create_chat_model",
        lambda settings: model,
    )
    container = composition.build_container()

    product = await container.product_repository.find_by_id("P1001")
    assert product is not None
    sku = product.find_sku("P1001-S1")
    assert sku is not None
    initial_stock = sku.stock

    placed = await container.place_order.execute(
        PlaceOrderInput(
            buyer_id="buyer-001",
            items=[
                OrderItemInput(
                    product_id="P1001",
                    sku_id="P1001-S1",
                    quantity=2,
                )
            ],
            shipping_address=Address(
                recipient_name="Alice",
                country="CN",
                state="上海",
                city="上海",
                address_line="南京西路 1 号",
                postal_code="200000",
                phone="13800000000",
            ),
        )
    )
    queried = await container.query_order.execute(
        QueryOrderInput(
            order_id=placed.order_id,
            buyer_id="buyer-001",
        )
    )

    assert sku.stock == initial_stock - 2
    assert queried.order_id == placed.order_id
    assert queried.status == "CONFIRMED"

    cancelled = await container.cancel_order.execute(
        CancelOrderInput(
            order_id=placed.order_id,
            buyer_id="buyer-001",
            reason="改变购买计划",
        )
    )

    assert cancelled.status == "CANCELLED"
    assert sku.stock == initial_stock
