from abc import ABC, abstractmethod

from app.domain.order.order import Order


class OrderRepository(ABC):
    @abstractmethod
    async def save(self, order: Order) -> None:
        ...

    @abstractmethod
    async def find_by_id(
        self,
        order_id: str,
    ) -> Order | None:
        ...

    @abstractmethod
    async def next_order_id(self) -> str:
        ...
        