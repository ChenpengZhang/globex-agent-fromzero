import json

import pytest

from agentscope.message import ToolResultState
from agentscope.tool import FunctionTool

from app.application.tools.product_search_tool import (
    build_product_search_tool,
)
from app.application.usecases.catalog_search import (
    CatalogSearchUseCase,
)
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import (
    build_seed_products,
)


def build_tool_function():
    repository = InMemoryProductRepository(
        build_seed_products(),
    )
    usecase = CatalogSearchUseCase(repository)

    return build_product_search_tool(usecase)


def test_function_tool_generates_expected_schema() -> None:
    function_tool = FunctionTool(
        build_tool_function(),
        is_read_only=True,
    )

    assert function_tool.name == "product_search_tool"

    assert function_tool.input_schema["required"] == [
        "normalized_query",
    ]

    assert set(
        function_tool.input_schema["properties"],
    ) == {
        "normalized_query",
        "category",
        "ship_to",
        "top_k",
        "price_max_major",
        "target_currency",
    }


@pytest.mark.asyncio
async def test_product_search_tool_returns_json() -> None:
    tool_function = build_tool_function()

    result = await tool_function(
        normalized_query="旅行 轻便",
        category="旅行装备",
        ship_to="CN",
        price_max_major=300,
    )

    assert result.state == ToolResultState.SUCCESS

    payload = json.loads(
        result.content[0].text,
    )

    assert [
        hit["product_id"]
        for hit in payload["hits"]
    ] == [
        "P1001",
        "P1003",
    ]

    assert payload["filtered_out"][0]["product_id"] == "P1002"
    assert (
        payload["filtered_out"][0]["reason"]
        == "over_price_cap"
    )


@pytest.mark.asyncio
async def test_product_search_tool_returns_error_chunk() -> None:
    tool_function = build_tool_function()

    result = await tool_function(
        normalized_query="",
    )

    assert result.state == ToolResultState.ERROR
    assert result.content[0].text.startswith("[error]")