import json

import pytest

from agentscope.message import (
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    UserMsg,
)
from agentscope.model import ChatResponse
from agentscope.tool import FunctionTool

from app.application.agents.main_agent import create_main_agent
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
from tests.fakes import ScriptedChatModel


def collect_tool_result_texts(messages) -> list[str]:
    texts: list[str] = []

    for message in messages:
        for block in message.get_content_blocks():
            if not isinstance(block, ToolResultBlock):
                continue

            if isinstance(block.output, str):
                texts.append(block.output)
                continue

            texts.extend(
                item.text
                for item in block.output
                if isinstance(item, TextBlock)
            )

    return texts


@pytest.mark.asyncio
async def test_agent_executes_tool_and_observes_result() -> None:
    first_model_response = ChatResponse(
        content=[
            ToolCallBlock(
                id="call-product-search-1",
                name="product_search_tool",
                input=json.dumps(
                    {
                        "normalized_query": "旅行 轻便",
                        "category": "旅行装备",
                        "ship_to": "CN",
                        "top_k": 5,
                        "price_max_major": 300,
                        "target_currency": "CNY",
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
        is_last=True,
    )

    second_model_response = ChatResponse(
        content=[
            TextBlock(
                type="text",
                text=(
                    "推荐 P1001 和 P1003，"
                    "它们都在 300 CNY 预算内。"
                ),
            ),
        ],
        is_last=True,
    )

    model = ScriptedChatModel(
        responses=[
            first_model_response,
            second_model_response,
        ],
    )

    repository = InMemoryProductRepository(
        build_seed_products(),
    )
    usecase = CatalogSearchUseCase(repository)

    tool = FunctionTool(
        build_product_search_tool(usecase),
        is_read_only=True,
    )

    agent = create_main_agent(
        model=model,
        tools=[tool],
    )

    reply = await agent.reply(
        [
            UserMsg(
                name="buyer",
                content=(
                    "推荐 300 元以内、"
                    "能寄到中国的轻便旅行装备"
                ),
            ),
        ],
    )

    assert len(model.calls) == 2

    first_call_tools = model.calls[0]["tools"]

    assert any(
        item["function"]["name"]
        == "product_search_tool"
        for item in first_call_tools
    )

    second_call_messages = model.calls[1]["messages"]
    tool_result_texts = collect_tool_result_texts(
        second_call_messages,
    )

    assert any(
        "P1001" in text
        and "P1003" in text
        and "over_price_cap" in text
        for text in tool_result_texts
    )

    assert reply.get_text_content() == (
        "推荐 P1001 和 P1003，"
        "它们都在 300 CNY 预算内。"
    )