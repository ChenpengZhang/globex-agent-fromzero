from app.application.dto.order import (
    CancelOrderInput,
    OrderOutput,
    to_order_output,
)
from app.application.usecases.order_access import (
    load_owned_order,
)
from app.domain.catalog.ports.product_repository import (
    ProductRepository,
)
from app.domain.catalog.sku import Sku
from app.domain.order.ports.order_repository import (
    OrderRepository,
)


class CancelOrderUseCase:
    def __init__(
        self,
        product_repository: ProductRepository,
        order_repository: OrderRepository,
    ) -> None:
        self._product_repository = product_repository
        self._order_repository = order_repository

    async def execute(
        self,
        command: CancelOrderInput,
    ) -> OrderOutput:
        order = await load_owned_order(
            order_repository=self._order_repository,
            order_id=command.order_id,
            buyer_id=command.buyer_id,
        )

        inventory_to_restore: list[tuple[Sku, int]] = []

        for line in order.lines:
            product = (
                await self._product_repository.find_by_id(
                    line.product_id,
                )
            )

            if product is None:
                raise ValueError(
                    f"无法回补库存，商品不存在: "
                    f"{line.product_id}"
                )

            sku = product.find_sku(line.sku_id)

            if sku is None:
                raise ValueError(
                    f"无法回补库存，SKU 不存在: "
                    f"{line.product_id}/{line.sku_id}"
                )

            inventory_to_restore.append(
                (sku, line.quantity)
            )

        order.cancel(command.reason)

        for sku, quantity in inventory_to_restore:
            sku.restore_stock(quantity)

        await self._order_repository.save(order)

        return to_order_output(order)
    