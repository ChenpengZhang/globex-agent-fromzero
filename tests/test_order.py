from datetime import timezone

import pytest

from app.domain.catalog.money import Money
from app.domain.order.address import Address
from app.domain.order.order import Order, OrderStatus
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


def make_line(
    *,
    sku_id: str = "sku-black",
    amount_minor: int = 19_990,
    currency: str = "CNY",
    quantity: int = 2,
) -> OrderLine:
    return OrderLine(
        product_id="product-001",
        sku_id=sku_id,
        title=f"旅行背包 - {sku_id}",
        unit_price=Money(
            amount_minor=amount_minor,
            currency=currency,
        ),
        quantity=quantity,
    )


def make_order(**overrides: object) -> Order:
    values: dict[str, object] = {
        "order_id": " order-001 ",
        "buyer_id": " buyer-001 ",
        "shipping_address": make_address(),
        "lines": [make_line()],
    }
    values.update(overrides)
    return Order(**values)  # type: ignore[arg-type]


def test_new_order_is_normalized_draft() -> None:
    order = make_order()

    assert order.order_id == "order-001"
    assert order.buyer_id == "buyer-001"
    assert order.status is OrderStatus.DRAFT
    assert order.created_at.tzinfo is timezone.utc
    assert order.confirmed_at is None
    assert order.cancelled_at is None
    assert order.cancel_reason is None


@pytest.mark.parametrize("field_name", ["order_id", "buyer_id"])
def test_order_rejects_blank_identity_fields(field_name: str) -> None:
    with pytest.raises(ValueError, match="不能为空"):
        make_order(**{field_name: "   "})


def test_order_requires_at_least_one_line() -> None:
    with pytest.raises(ValueError, match="至少需要一条"):
        make_order(lines=[])


def test_order_rejects_lines_with_different_currencies() -> None:
    with pytest.raises(ValueError, match="相同币种"):
        make_order(
            lines=[
                make_line(currency="CNY"),
                make_line(sku_id="sku-us", currency="USD"),
            ]
        )


def test_order_protects_lines_from_external_list_changes() -> None:
    source_lines = [make_line()]
    order = make_order(lines=source_lines)

    source_lines.append(make_line(sku_id="sku-blue"))

    assert isinstance(order.lines, tuple)
    assert len(order.lines) == 1


def test_order_calculates_total_from_line_subtotals() -> None:
    order = make_order(
        lines=[
            make_line(amount_minor=10_000, quantity=2),
            make_line(
                sku_id="sku-blue",
                amount_minor=2_500,
                quantity=3,
            ),
        ]
    )

    assert order.total_amount() == Money(
        amount_minor=27_500,
        currency="CNY",
    )


def test_confirm_changes_draft_to_confirmed() -> None:
    order = make_order()

    order.confirm()

    assert order.status is OrderStatus.CONFIRMED
    assert order.confirmed_at is not None
    assert order.confirmed_at.tzinfo is timezone.utc


def test_confirm_rejects_non_draft_order() -> None:
    order = make_order()
    order.confirm()

    with pytest.raises(ValueError, match="只有草稿订单"):
        order.confirm()


def test_draft_order_cannot_be_cancelled() -> None:
    order = make_order()

    with pytest.raises(ValueError, match="只有已确认订单"):
        order.cancel("不再需要")


def test_confirmed_order_requires_cancellation_reason() -> None:
    order = make_order()
    order.confirm()

    with pytest.raises(ValueError, match="必须提供原因"):
        order.cancel("   ")

    assert order.status is OrderStatus.CONFIRMED


def test_cancel_changes_confirmed_order_to_cancelled() -> None:
    order = make_order()
    order.confirm()

    order.cancel("  用户不再需要  ")

    assert order.status is OrderStatus.CANCELLED
    assert order.cancel_reason == "用户不再需要"
    assert order.cancelled_at is not None
    assert order.cancelled_at.tzinfo is timezone.utc


def test_cancelled_order_cannot_be_cancelled_again() -> None:
    order = make_order()
    order.confirm()
    order.cancel("用户不再需要")

    with pytest.raises(ValueError, match="只有已确认订单"):
        order.cancel("再次取消")


def test_place_returns_confirmed_order() -> None:
    order = Order.place(
        order_id="order-001",
        buyer_id="buyer-001",
        shipping_address=make_address(),
        lines=[make_line()],
    )

    assert order.status is OrderStatus.CONFIRMED
    assert order.confirmed_at is not None
