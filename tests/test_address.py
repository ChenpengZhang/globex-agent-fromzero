from dataclasses import FrozenInstanceError

import pytest

from app.domain.order.address import Address


def make_address(**overrides: str) -> Address:
    values = {
        "recipient_name": " Alice ",
        "country": "us",
        "state": " New York ",
        "city": " New York City ",
        "address_line": " 123 Broadway ",
        "postal_code": " 10001 ",
        "phone": " +1 212 555 0100 ",
    }
    values.update(overrides)
    return Address(**values)


def test_address_normalizes_text_and_country_code() -> None:
    address = make_address()

    assert address.recipient_name == "Alice"
    assert address.country == "US"
    assert address.state == "New York"
    assert address.city == "New York City"
    assert address.address_line == "123 Broadway"
    assert address.postal_code == "10001"
    assert address.phone == "+1 212 555 0100"


def test_address_is_immutable() -> None:
    address = make_address()

    with pytest.raises(FrozenInstanceError):
        address.city = "Boston"  # type: ignore[misc]


def test_one_line_omits_empty_state() -> None:
    address = make_address(state="")

    assert address.one_line() == (
        "US, New York City, 123 Broadway, 10001 "
        "(Alice, +1 212 555 0100)"
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "recipient_name",
        "country",
        "city",
        "address_line",
        "postal_code",
        "phone",
    ],
)
def test_address_rejects_blank_required_fields(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_address(**{field_name: "   "})


@pytest.mark.parametrize("country", ["U", "USA"])
def test_address_rejects_invalid_country_code(country: str) -> None:
    with pytest.raises(ValueError, match="两个字符"):
        make_address(country=country)
