from app.application.dto.order import (
    OrderOutput,
    PlaceOrderInput,
    to_order_output,
)
from app.domain.catalog.ports.product_repository import (
    ProductRepository,
)
from app.domain.catalog.sku import Sku
from app.domain.order.order import Order
from app.domain.order.order_line import OrderLine
from app.domain.order.ports.order_repository import (
    OrderRepository,
)


class PlaceOrderUseCase:
    def __init__(
        self,
        product_repository: ProductRepository,
        order_repository: OrderRepository,
    ) -> None:
        self._product_repository = product_repository
        self._order_repository = order_repository

    async def execute(
        self,
        command: PlaceOrderInput,
    ) -> OrderOutput:
        lines: list[OrderLine] = []
        deducted_inventory: list[tuple[Sku, int]] = []
        order_saved = False

        try:
            for item in command.items:
                product = (
                    await self._product_repository.find_by_id(
                        item.product_id,
                    )
                )

                if product is None:
                    raise ValueError(
                        f"商品不存在: {item.product_id}"
                    )

                if (
                    command.shipping_address.country
                    not in product.ships_to
                ):
                    raise ValueError(
                        f"商品无法配送到 "
                        f"{command.shipping_address.country}: "
                        f"{product.product_id}"
                    )

                sku = product.find_sku(item.sku_id)

                if sku is None:
                    raise ValueError(
                        f"SKU 不存在: "
                        f"{product.product_id}/{item.sku_id}"
                    )

                sku.deduct_stock(item.quantity)

                deducted_inventory.append(
                    (sku, item.quantity)
                )

                lines.append(
                    OrderLine(
                        product_id=product.product_id,
                        sku_id=sku.sku_id,
                        title=(
                            f"{product.title} "
                            f"({sku.spec})"
                        ),
                        unit_price=sku.price,
                        quantity=item.quantity,
                    )
                )

            order_id = (
                await self._order_repository.next_order_id()
            )

            order = Order.place(
                order_id=order_id,
                buyer_id=command.buyer_id,
                shipping_address=command.shipping_address,
                lines=lines,
            )

            await self._order_repository.save(order)
            order_saved = True

        finally:
            if not order_saved:
                for sku, quantity in reversed(
                    deducted_inventory
                ):
                    sku.restore_stock(quantity)
        # The partial reason we use finally and order_saved flag here is that
        # we don't want to rollback the inventory deduction 
        # if the order is completed (in most cases, after transaction)

        return to_order_output(order)
    