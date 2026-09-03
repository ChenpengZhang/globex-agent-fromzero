from datetime import datetime

import pytest

from app.application.dto.order import (
    CancelOrderInput,
    OrderItemInput,
    PlaceOrderInput,
    QueryOrderInput,
    to_order_output,
)
from app.domain.catalog.money import Money
from app.domain.order.address import Address
from app.domain.order.order import Order
from app.domain.order.order_line import OrderLine


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


def make_order() -> Order:
    return Order.place(
        order_id="GBX-000001",
        buyer_id="buyer-001",
        shipping_address=make_address(),
        lines=[
            OrderLine(
                product_id="product-001",
                sku_id="sku-black",
                title="轻便旅行背包 - black",
                unit_price=Money.from_major_units("199.90", "CNY"),
                quantity=2,
            ),
            OrderLine(
                product_id="product-002",
                sku_id="sku-blue",
                title="旅行收纳包 - blue",
                unit_price=Money.from_major_units("20", "CNY"),
                quantity=1,
            ),
        ],
    )


def test_order_item_input_normalizes_identifiers() -> None:
    item = OrderItemInput(
        product_id=" product-001 ",
        sku_id=" sku-black ",
        quantity=2,
    )

    assert item.product_id == "product-001"
    assert item.sku_id == "sku-black"


@pytest.mark.parametrize("field_name", ["product_id", "sku_id"])
def test_order_item_input_rejects_blank_identifiers(field_name: str) -> None:
    values = {
        "product_id": "product-001",
        "sku_id": "sku-black",
        "quantity": 1,
    }
    values[field_name] = "   "

    with pytest.raises(ValueError, match=field_name):
        OrderItemInput(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True])
def test_order_item_input_rejects_invalid_quantity(quantity: object) -> None:
    with pytest.raises(ValueError, match="正整数"):
        OrderItemInput(
            product_id="product-001",
            sku_id="sku-black",
            quantity=quantity,  # type: ignore[arg-type]
        )


def test_place_order_input_normalizes_buyer_and_freezes_items() -> None:
    source_items = [
        OrderItemInput(
            product_id="product-001",
            sku_id="sku-black",
            quantity=1,
        )
    ]
    command = PlaceOrderInput(
        buyer_id=" buyer-001 ",
        items=source_items,
        shipping_address=make_address(),
    )

    source_items.append(
        OrderItemInput(
            product_id="product-002",
            sku_id="sku-blue",
            quantity=1,
        )
    )

    assert command.buyer_id == "buyer-001"
    assert isinstance(command.items, tuple)
    assert len(command.items) == 1


def test_place_order_input_rejects_empty_items() -> None:
    with pytest.raises(ValueError, match="items"):
        PlaceOrderInput(
            buyer_id="buyer-001",
            items=[],
            shipping_address=make_address(),
        )


def test_query_order_input_normalizes_identity() -> None:
    query = QueryOrderInput(
        order_id=" GBX-000001 ",
        buyer_id=" buyer-001 ",
    )

    assert query.order_id == "GBX-000001"
    assert query.buyer_id == "buyer-001"


def test_cancel_order_input_normalizes_identity_and_reason() -> None:
    command = CancelOrderInput(
        order_id=" GBX-000001 ",
        buyer_id=" buyer-001 ",
        reason=" 不再需要 ",
    )

    assert command.order_id == "GBX-000001"
    assert command.buyer_id == "buyer-001"
    assert command.reason == "不再需要"


@pytest.mark.parametrize("field_name", ["order_id", "buyer_id", "reason"])
def test_cancel_order_input_rejects_blank_fields(field_name: str) -> None:
    values = {
        "order_id": "GBX-000001",
        "buyer_id": "buyer-001",
        "reason": "不再需要",
    }
    values[field_name] = "   "

    with pytest.raises(ValueError, match=field_name):
        CancelOrderInput(**values)


def test_to_order_output_creates_serializable_snapshot() -> None:
    order = make_order()

    output = to_order_output(order)

    assert output.order_id == "GBX-000001"
    assert output.buyer_id == "buyer-001"
    assert output.status == "CONFIRMED"
    assert output.shipping_address.country == "US"
    assert output.total_amount.amount_minor == 41_980
    assert output.total_amount.amount_major == "419.80"
    assert output.total_amount.currency == "CNY"
    assert output.lines[0].unit_price.amount_major == "199.90"
    assert output.lines[0].subtotal.amount_major == "399.80"
    assert output.lines[1].subtotal.amount_major == "20.00"
    assert datetime.fromisoformat(output.created_at).tzinfo is not None
    assert output.confirmed_at is not None
    assert datetime.fromisoformat(output.confirmed_at).tzinfo is not None
    assert output.cancelled_at is None
    assert output.cancel_reason is None


def test_to_order_output_includes_cancellation_snapshot() -> None:
    order = make_order()
    order.cancel("用户不再需要")

    output = to_order_output(order)

    assert output.status == "CANCELLED"
    assert output.cancelled_at is not None
    assert datetime.fromisoformat(output.cancelled_at).tzinfo is not None
    assert output.cancel_reason == "用户不再需要"
