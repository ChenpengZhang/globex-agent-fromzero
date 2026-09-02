from dataclasses import FrozenInstanceError

import pytest

from app.domain.catalog.money import Money
from app.domain.order.order_line import OrderLine


def make_order_line(**overrides: object) -> OrderLine:
    values: dict[str, object] = {
        "product_id": " product-001 ",
        "sku_id": " sku-black ",
        "title": " 轻便旅行背包 - 黑色 ",
        "unit_price": Money.from_major_units("199.90", "CNY"),
        "quantity": 2,
    }
    values.update(overrides)
    return OrderLine(**values)  # type: ignore[arg-type]


def test_order_line_normalizes_snapshot_fields() -> None:
    line = make_order_line()

    assert line.product_id == "product-001"
    assert line.sku_id == "sku-black"
    assert line.title == "轻便旅行背包 - 黑色"


def test_order_line_calculates_subtotal_with_money() -> None:
    line = make_order_line()

    assert line.subtotal() == Money(
        amount_minor=39_980,
        currency="CNY",
    )


def test_order_line_is_immutable() -> None:
    line = make_order_line()

    with pytest.raises(FrozenInstanceError):
        line.quantity = 3  # type: ignore[misc]


@pytest.mark.parametrize("field_name", ["product_id", "sku_id", "title"])
def test_order_line_rejects_blank_snapshot_fields(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_order_line(**{field_name: "   "})


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True])
def test_order_line_rejects_invalid_quantity(quantity: object) -> None:
    with pytest.raises(ValueError, match="正整数"):
        make_order_line(quantity=quantity)
