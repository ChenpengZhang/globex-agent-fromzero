import itertools

from app.domain.order.order import Order
from app.domain.order.ports.order_repository import (
    OrderRepository,
)


class InMemoryOrderRepository(OrderRepository):
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._counter = itertools.count(1)

    async def save(self, order: Order) -> None:
        # As for now we are pointing to the same order instance anyway,
        # the order will actually update itself without reassigning.
        # so this is just a demo which is not needed
        # just to show the logic
        self._orders[order.order_id] = order

    async def find_by_id(
        self,
        order_id: str,
    ) -> Order | None:
        return self._orders.get(order_id)

    async def next_order_id(self) -> str:
        sequence = next(self._counter)
        return f"GBX-{sequence:06d}"
    