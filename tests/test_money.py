import pytest

from app.domain.catalog.money import Money


def test_add_returns_new_money_with_same_currency() -> None:
    left = Money(amount_minor=1_999, currency="usd")
    right = Money(amount_minor=501, currency="USD")

    result = left.add(right)

    assert result == Money(amount_minor=2_500, currency="USD")
    assert left == Money(amount_minor=1_999, currency="USD")


def test_add_rejects_different_currencies() -> None:
    with pytest.raises(ValueError, match="不同币种"):
        Money(amount_minor=100, currency="USD").add(
            Money(amount_minor=100, currency="CNY")
        )


@pytest.mark.parametrize(
    ("quantity", "expected_amount_minor"),
    [
        (0, 0),
        (3, 5_997),
    ],
)
def test_multiply_by_non_negative_integer(
    quantity: int,
    expected_amount_minor: int,
) -> None:
    price = Money(amount_minor=1_999, currency="USD")

    result = price.multiply(quantity)

    assert result == Money(
        amount_minor=expected_amount_minor,
        currency="USD",
    )


@pytest.mark.parametrize("quantity", [-1, 1.5, True])
def test_multiply_rejects_invalid_quantity(quantity: object) -> None:
    with pytest.raises(ValueError, match="非负整数"):
        Money(amount_minor=1_999, currency="USD").multiply(quantity)  # type: ignore[arg-type]
