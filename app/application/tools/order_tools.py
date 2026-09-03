import json
from dataclasses import asdict

from agentscope.message import (
    TextBlock,
    ToolResultState,
)
from agentscope.tool import ToolChunk

from app.application.dto.order import (
    CancelOrderInput,
    OrderItemInput,
    OrderOutput,
    PlaceOrderInput,
    QueryOrderInput,
)
from app.application.usecases.cancel_order import (
    CancelOrderUseCase,
)
from app.application.usecases.place_order import (
    PlaceOrderUseCase,
)
from app.application.usecases.query_order import (
    QueryOrderUseCase,
)
from app.domain.order.address import Address
from app.infrastructure.context import ShoppingContext


def _success(output: OrderOutput) -> ToolChunk:
    return ToolChunk(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(
                    asdict(output),
                    ensure_ascii=False,
                ),
            ),
        ],
        state=ToolResultState.SUCCESS,
    )


def _failure(error: Exception) -> ToolChunk:
    return ToolChunk(
        content=[
            TextBlock(
                type="text",
                text=f"[error] {error}",
            ),
        ],
        state=ToolResultState.ERROR,
    )


def build_place_order_tool(
    use_case: PlaceOrderUseCase,
):
    async def place_order_tool(
        items: list[dict],
        shipping_address: dict,
    ) -> ToolChunk:
        """Place a confirmed order after explicit user confirmation.

        Never call this tool until the user has explicitly confirmed
        the exact items, quantities, known unit prices, and shipping address.
        Buyer identity is injected by the current request context.

        Args:
            items (`list[dict]`):
                Order items. Each item must contain product_id,
                sku_id, and a positive integer quantity.
            shipping_address (`dict`):
                Shipping address containing recipient_name,
                country, state, city, address_line,
                postal_code, and phone.
        """
        try:
            context = ShoppingContext.require_current()

            order_items = [
                OrderItemInput(
                    product_id=item["product_id"],
                    sku_id=item["sku_id"],
                    quantity=item.get("quantity", 1),
                )
                for item in items
            ]

            address = Address(
                recipient_name=shipping_address.get(
                    "recipient_name",
                    "",
                ),
                country=shipping_address.get(
                    "country",
                    "",
                ),
                state=shipping_address.get(
                    "state",
                    "",
                ),
                city=shipping_address.get(
                    "city",
                    "",
                ),
                address_line=shipping_address.get(
                    "address_line",
                    "",
                ),
                postal_code=shipping_address.get(
                    "postal_code",
                    "",
                ),
                phone=shipping_address.get(
                    "phone",
                    "",
                ),
            )

            output = await use_case.execute(
                PlaceOrderInput(
                    buyer_id=context.buyer_id,
                    items=order_items,
                    shipping_address=address,
                )
            )

        except (
            ValueError,
            PermissionError,
            KeyError,
            TypeError,
            RuntimeError,
        ) as error:
            return _failure(error)

        return _success(output)

    return place_order_tool


def build_query_order_tool(
    use_case: QueryOrderUseCase,
):
    async def query_order_tool(
        order_id: str,
    ) -> ToolChunk:
        """Query an order owned by the current buyer.

        Buyer identity is injected by the current request context.

        Args:
            order_id (`str`):
                Order ID such as "GBX-000001".
        """
        try:
            context = ShoppingContext.require_current()

            output = await use_case.execute(
                QueryOrderInput(
                    order_id=order_id,
                    buyer_id=context.buyer_id,
                )
            )

        except (
            ValueError,
            PermissionError,
            TypeError,
            RuntimeError,
        ) as error:
            return _failure(error)

        return _success(output)

    return query_order_tool


def build_cancel_order_tool(
    use_case: CancelOrderUseCase,
):
    async def cancel_order_tool(
        order_id: str,
        reason: str,
    ) -> ToolChunk:
        """Cancel a confirmed order and restore its inventory.

        Buyer identity is injected by the current request context.

        Args:
            order_id (`str`):
                Order ID such as "GBX-000001".
            reason (`str`):
                Required cancellation reason.
        """
        try:
            context = ShoppingContext.require_current()

            output = await use_case.execute(
                CancelOrderInput(
                    order_id=order_id,
                    buyer_id=context.buyer_id,
                    reason=reason,
                )
            )

        except (
            ValueError,
            PermissionError,
            TypeError,
            RuntimeError,
        ) as error:
            return _failure(error)

        return _success(output)

    return cancel_order_tool
