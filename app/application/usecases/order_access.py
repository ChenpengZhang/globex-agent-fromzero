from app.domain.order.order import Order
from app.domain.order.ports.order_repository import (
    OrderRepository,
)


class OrderNotFoundError(ValueError):
    pass


class OrderAccessDeniedError(PermissionError):
    pass


async def load_owned_order(
    order_repository: OrderRepository,
    order_id: str,
    buyer_id: str,
) -> Order:
    order = await order_repository.find_by_id(order_id)

    if order is None:
        raise OrderNotFoundError(
            f"订单不存在: {order_id}"
        )

    if order.buyer_id != buyer_id:
        raise OrderAccessDeniedError(
            f"买家无权访问订单: {order_id}"
        )

    return order
