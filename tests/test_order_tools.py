import json
from contextlib import contextmanager
from typing import Iterator

import pytest

from agentscope.message import ToolResultState
from agentscope.tool import FunctionTool

from app.application.tools.order_tools import (
    build_cancel_order_tool,
    build_place_order_tool,
    build_query_order_tool,
)
from app.application.usecases.cancel_order import CancelOrderUseCase
from app.application.usecases.place_order import PlaceOrderUseCase
from app.application.usecases.query_order import QueryOrderUseCase
from app.infrastructure.context import (
    ShoppingContext,
    ShoppingContextSnapshot,
)
from app.infrastructure.persistence.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import build_seed_products


@contextmanager
def shopping_context(
    buyer_id: str,
) -> Iterator[None]:
    reset_token = ShoppingContext.set(
        ShoppingContextSnapshot(
            shopping_session_id=f"session-{buyer_id}",
            buyer_id=buyer_id,
            locale="zh-CN",
            currency="CNY",
        )
    )
    try:
        yield
    finally:
        ShoppingContext.reset(reset_token)


def build_tool_functions():
    product_repository = InMemoryProductRepository(
        build_seed_products()
    )
    order_repository = InMemoryOrderRepository()

    return (
        build_place_order_tool(
            PlaceOrderUseCase(
                product_repository,
                order_repository,
            )
        ),
        build_query_order_tool(
            QueryOrderUseCase(order_repository)
        ),
        build_cancel_order_tool(
            CancelOrderUseCase(
                product_repository,
                order_repository,
            )
        ),
        product_repository,
        order_repository,
    )


def shipping_address() -> dict:
    return {
        "recipient_name": "Alice",
        "country": "CN",
        "state": "上海",
        "city": "上海",
        "address_line": "南京西路 1 号",
        "postal_code": "200000",
        "phone": "13800000000",
    }


def test_order_function_tools_generate_safe_schemas() -> None:
    place, query, cancel, _, _ = build_tool_functions()

    place_tool = FunctionTool(place, is_read_only=False)
    query_tool = FunctionTool(query, is_read_only=True)
    cancel_tool = FunctionTool(cancel, is_read_only=False)

    assert place_tool.name == "place_order_tool"
    assert place_tool.input_schema["required"] == [
        "items",
        "shipping_address",
    ]
    assert "buyer_id" not in place_tool.input_schema["properties"]

    assert query_tool.name == "query_order_tool"
    assert query_tool.input_schema["required"] == ["order_id"]
    assert "buyer_id" not in query_tool.input_schema["properties"]

    assert cancel_tool.name == "cancel_order_tool"
    assert cancel_tool.input_schema["required"] == [
        "order_id",
        "reason",
    ]
    assert "buyer_id" not in cancel_tool.input_schema["properties"]


@pytest.mark.asyncio
async def test_order_tools_complete_place_query_cancel_flow() -> None:
    place, query, cancel, product_repository, _ = build_tool_functions()
    product = await product_repository.find_by_id("P1001")
    assert product is not None
    sku = product.find_sku("P1001-S1")
    assert sku is not None
    initial_stock = sku.stock

    with shopping_context("buyer-001"):
        placed_result = await place(
            items=[
                {
                    "product_id": "P1001",
                    "sku_id": "P1001-S1",
                    "quantity": 2,
                }
            ],
            shipping_address=shipping_address(),
        )
        placed = json.loads(placed_result.content[0].text)

        queried_result = await query(placed["order_id"])
        queried = json.loads(queried_result.content[0].text)

        cancelled_result = await cancel(
            placed["order_id"],
            "改变购买计划",
        )
        cancelled = json.loads(cancelled_result.content[0].text)

    assert placed_result.state == ToolResultState.SUCCESS
    assert placed["buyer_id"] == "buyer-001"
    assert placed["status"] == "CONFIRMED"
    assert queried_result.state == ToolResultState.SUCCESS
    assert queried["order_id"] == placed["order_id"]
    assert cancelled_result.state == ToolResultState.SUCCESS
    assert cancelled["status"] == "CANCELLED"
    assert sku.stock == initial_stock


@pytest.mark.asyncio
async def test_order_tools_enforce_context_buyer_ownership() -> None:
    place, query, cancel, product_repository, _ = build_tool_functions()
    product = await product_repository.find_by_id("P1001")
    assert product is not None
    sku = product.find_sku("P1001-S1")
    assert sku is not None

    with shopping_context("buyer-001"):
        placed_result = await place(
            items=[
                {
                    "product_id": "P1001",
                    "sku_id": "P1001-S1",
                    "quantity": 1,
                }
            ],
            shipping_address=shipping_address(),
        )
        order_id = json.loads(
            placed_result.content[0].text
        )["order_id"]

    stock_after_place = sku.stock

    with shopping_context("buyer-002"):
        query_result = await query(order_id)
        cancel_result = await cancel(order_id, "尝试取消")

    assert query_result.state == ToolResultState.ERROR
    assert "无权访问" in query_result.content[0].text
    assert cancel_result.state == ToolResultState.ERROR
    assert "无权访问" in cancel_result.content[0].text
    assert sku.stock == stock_after_place


@pytest.mark.asyncio
async def test_place_order_tool_returns_validation_error_without_deduction() -> None:
    place, _, _, product_repository, _ = build_tool_functions()
    product = await product_repository.find_by_id("P1001")
    assert product is not None
    sku = product.find_sku("P1001-S1")
    assert sku is not None
    initial_stock = sku.stock
    invalid_address = shipping_address()
    invalid_address["city"] = ""

    with shopping_context("buyer-001"):
        result = await place(
            items=[
                {
                    "product_id": "P1001",
                    "sku_id": "P1001-S1",
                    "quantity": 1,
                }
            ],
            shipping_address=invalid_address,
        )

    assert result.state == ToolResultState.ERROR
    assert result.content[0].text.startswith("[error]")
    assert sku.stock == initial_stock


@pytest.mark.asyncio
async def test_order_tool_requires_request_context() -> None:
    _, query, _, _, _ = build_tool_functions()

    result = await query("GBX-000001")

    assert result.state == ToolResultState.ERROR
    assert "缺少 ShoppingContext" in result.content[0].text
