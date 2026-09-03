import pytest

from app.domain.catalog.money import Money
from app.domain.catalog.sku import Sku


def make_sku(*, stock: object = 5) -> Sku:
    return Sku(
        sku_id="sku-black",
        spec="black",
        price=Money.from_major_units("199.90", "CNY"),
        stock=stock,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("stock", [-1, 1.5, True])
def test_sku_rejects_invalid_initial_stock(stock: object) -> None:
    with pytest.raises(ValueError, match="非负整数"):
        make_sku(stock=stock)


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        (1, True),
        (5, True),
        (6, False),
        (0, False),
        (-1, False),
        (1.5, False),
        (True, False),
    ],
)
def test_is_available_is_a_safe_inventory_query(
    quantity: object,
    expected: bool,
) -> None:
    sku = make_sku()

    assert sku.is_available(quantity) is expected  # type: ignore[arg-type]


def test_deduct_stock_reduces_available_stock() -> None:
    sku = make_sku()

    sku.deduct_stock(2)

    assert sku.stock == 3


def test_deduct_stock_rejects_insufficient_stock_without_mutation() -> None:
    sku = make_sku()

    with pytest.raises(ValueError, match="库存不足"):
        sku.deduct_stock(6)

    assert sku.stock == 5


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True])
def test_deduct_stock_rejects_invalid_quantity_without_mutation(
    quantity: object,
) -> None:
    sku = make_sku()

    with pytest.raises(ValueError, match="正整数"):
        sku.deduct_stock(quantity)  # type: ignore[arg-type]

    assert sku.stock == 5


def test_restore_stock_adds_inventory_back() -> None:
    sku = make_sku()
    sku.deduct_stock(2)

    sku.restore_stock(2)

    assert sku.stock == 5


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True])
def test_restore_stock_rejects_invalid_quantity_without_mutation(
    quantity: object,
) -> None:
    sku = make_sku()

    with pytest.raises(ValueError, match="正整数"):
        sku.restore_stock(quantity)  # type: ignore[arg-type]

    assert sku.stock == 5
