from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.domain.catalog.money import Money
from app.domain.order.address import Address
from app.domain.order.order_line import OrderLine


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Order:
    order_id: str
    buyer_id: str
    shipping_address: Address
    lines: Sequence[OrderLine]

    status: OrderStatus = field(
        default=OrderStatus.DRAFT,
        init=False,
    )
    created_at: datetime = field(
        default_factory=_utc_now,
        init=False,
    )
    confirmed_at: datetime | None = field(
        default=None,
        init=False,
    )
    cancelled_at: datetime | None = field(
        default=None,
        init=False,
    )
    cancel_reason: str | None = field(
        default=None,
        init=False,
    )

    def __post_init__(self) -> None:
        normalized_order_id = self.order_id.strip()
        normalized_buyer_id = self.buyer_id.strip()

        if not normalized_order_id:
            raise ValueError("订单 ID 不能为空")

        if not normalized_buyer_id:
            raise ValueError("买家 ID 不能为空")

        if not self.lines:
            raise ValueError("订单至少需要一条订单行")

        normalized_lines = tuple(self.lines)

        currencies = {
            line.unit_price.currency
            for line in normalized_lines
        }

        if len(currencies) != 1:
            raise ValueError("同一订单的所有订单行必须使用相同币种")

        self.order_id = normalized_order_id
        self.buyer_id = normalized_buyer_id
        self.lines = normalized_lines

    @classmethod
    def place(
        cls,
        order_id: str,
        buyer_id: str,
        shipping_address: Address,
        lines: Sequence[OrderLine],
    ) -> "Order":
        order = cls(
            order_id=order_id,
            buyer_id=buyer_id,
            shipping_address=shipping_address,
            lines=lines,
        )
        order.confirm()
        return order

    def confirm(self) -> None:
        if self.status is not OrderStatus.DRAFT:
            raise ValueError(
                f"只有草稿订单可以确认，当前状态: {self.status.value}"
            )

        self.status = OrderStatus.CONFIRMED
        self.confirmed_at = _utc_now()

    def cancel(self, reason: str) -> None:
        if self.status is not OrderStatus.CONFIRMED:
            raise ValueError(
                f"只有已确认订单可以取消，当前状态: {self.status.value}"
            )

        normalized_reason = reason.strip()

        if not normalized_reason:
            raise ValueError("取消订单必须提供原因")

        self.status = OrderStatus.CANCELLED
        self.cancelled_at = _utc_now()
        self.cancel_reason = normalized_reason

    def total_amount(self) -> Money:
        total = self.lines[0].subtotal()

        for line in self.lines[1:]:
            total = total.add(line.subtotal())

        return total
    