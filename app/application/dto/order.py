from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.catalog.money import Money
from app.domain.order.address import Address
from app.domain.order.order import Order


def _required_text(
    value: str,
    field_name: str,
) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{field_name} 不能为空")

    return normalized


@dataclass(frozen=True)
class OrderItemInput:
    product_id: str
    sku_id: str
    quantity: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "product_id",
            _required_text(
                self.product_id,
                "product_id",
            ),
        )
        object.__setattr__(
            self,
            "sku_id",
            _required_text(
                self.sku_id,
                "sku_id",
            ),
        )

        if (
            not isinstance(self.quantity, int)
            or isinstance(self.quantity, bool)
            or self.quantity <= 0
        ):
            raise ValueError("quantity 必须是正整数")


@dataclass(frozen=True)
class PlaceOrderInput:
    buyer_id: str
    items: Sequence[OrderItemInput]
    shipping_address: Address

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "buyer_id",
            _required_text(
                self.buyer_id,
                "buyer_id",
            ),
        )

        if not self.items:
            raise ValueError("items 不能为空")

        object.__setattr__(
            self,
            "items",
            tuple(self.items),
        )


@dataclass(frozen=True)
class QueryOrderInput:
    order_id: str
    buyer_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "order_id",
            _required_text(
                self.order_id,
                "order_id",
            ),
        )
        object.__setattr__(
            self,
            "buyer_id",
            _required_text(
                self.buyer_id,
                "buyer_id",
            ),
        )


@dataclass(frozen=True)
class CancelOrderInput:
    order_id: str
    buyer_id: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "order_id",
            _required_text(
                self.order_id,
                "order_id",
            ),
        )
        object.__setattr__(
            self,
            "buyer_id",
            _required_text(
                self.buyer_id,
                "buyer_id",
            ),
        )
        object.__setattr__(
            self,
            "reason",
            _required_text(
                self.reason,
                "reason",
            ),
        )


@dataclass(frozen=True)
class MoneyOutput:
    amount_minor: int
    amount_major: str
    currency: str


@dataclass(frozen=True)
class AddressOutput:
    recipient_name: str
    country: str
    state: str
    city: str
    address_line: str
    postal_code: str
    phone: str


@dataclass(frozen=True)
class OrderLineOutput:
    product_id: str
    sku_id: str
    title: str
    quantity: int
    unit_price: MoneyOutput
    subtotal: MoneyOutput


@dataclass(frozen=True)
class OrderOutput:
    order_id: str
    buyer_id: str
    status: str
    shipping_address: AddressOutput
    lines: tuple[OrderLineOutput, ...]
    total_amount: MoneyOutput
    created_at: str
    confirmed_at: str | None
    cancelled_at: str | None
    cancel_reason: str | None


def _to_money_output(money: Money) -> MoneyOutput:
    return MoneyOutput(
        amount_minor=money.amount_minor,
        amount_major=f"{money.to_major_units():.2f}",
        currency=money.currency,
    )


def to_order_output(order: Order) -> OrderOutput:
    address = order.shipping_address

    return OrderOutput(
        order_id=order.order_id,
        buyer_id=order.buyer_id,
        status=order.status.value,
        shipping_address=AddressOutput(
            recipient_name=address.recipient_name,
            country=address.country,
            state=address.state,
            city=address.city,
            address_line=address.address_line,
            postal_code=address.postal_code,
            phone=address.phone,
        ),
        lines=tuple(
            OrderLineOutput(
                product_id=line.product_id,
                sku_id=line.sku_id,
                title=line.title,
                quantity=line.quantity,
                unit_price=_to_money_output(
                    line.unit_price,
                ),
                subtotal=_to_money_output(
                    line.subtotal(),
                ),
            )
            for line in order.lines
        ),
        total_amount=_to_money_output(
            order.total_amount(),
        ),
        created_at=order.created_at.isoformat(),
        confirmed_at=(
            order.confirmed_at.isoformat()
            if order.confirmed_at is not None
            else None
        ),
        cancelled_at=(
            order.cancelled_at.isoformat()
            if order.cancelled_at is not None
            else None
        ),
        cancel_reason=order.cancel_reason,
    )
