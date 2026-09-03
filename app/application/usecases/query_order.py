from app.application.dto.order import (
    OrderOutput,
    QueryOrderInput,
    to_order_output,
)
from app.application.usecases.order_access import (
    load_owned_order,
)
from app.domain.order.ports.order_repository import (
    OrderRepository,
)


class QueryOrderUseCase:
    def __init__(
        self,
        order_repository: OrderRepository,
    ) -> None:
        self._order_repository = order_repository

    async def execute(
        self,
        query: QueryOrderInput,
    ) -> OrderOutput:
        order = await load_owned_order(
            order_repository=self._order_repository,
            order_id=query.order_id,
            buyer_id=query.buyer_id,
        )

        return to_order_output(order)