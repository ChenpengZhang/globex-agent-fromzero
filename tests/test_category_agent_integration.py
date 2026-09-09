import json

import pytest

from agentscope.message import (
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    UserMsg,
)
from agentscope.model import ChatResponse
from agentscope.rag import Chunk
from agentscope.rag._vdb import VectorSearchResult

from app.application.agents.search_agent import SearchAgentFactory
from app.application.usecases.catalog_search import CatalogSearchUseCase
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import build_seed_products
from tests.fakes import ScriptedChatModel


class RecordingKnowledgeBase:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def search(
        self,
        queries: list[str],
        top_k: int,
    ) -> list[VectorSearchResult]:
        self.calls.append(
            {
                "queries": queries,
                "top_k": top_k,
            }
        )

        return [
            VectorSearchResult(
                score=0.91325,
                document_id="travel-gear",
                chunk=Chunk(
                    content=TextBlock(
                        type="text",
                        text=(
                            "选择登机箱时要核对航空公司的尺寸限制，"
                            "并关注箱体自重和轮组耐用性。"
                        ),
                    ),
                    source="travel-gear.md",
                    chunk_index=0,
                    total_chunks=1,
                    metadata={
                        "source": "travel-gear.md",
                    },
                ),
            )
        ]


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
async def test_search_agent_retrieves_category_knowledge_before_answering(
) -> None:
    model = ScriptedChatModel(
        responses=[
            ChatResponse(
                content=[
                    ToolCallBlock(
                        id="call-category-insight-1",
                        name="category_insight_tool",
                        input=json.dumps(
                            {
                                "question": "登机箱应该怎么挑",
                                "top_k": 2,
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
                is_last=True,
            ),
            ChatResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "挑选登机箱时，先核对航司尺寸限制，"
                            "再比较箱体自重和轮组耐用性。"
                        ),
                    )
                ],
                is_last=True,
            ),
        ]
    )
    knowledge_base = RecordingKnowledgeBase()
    catalog_search = CatalogSearchUseCase(
        InMemoryProductRepository(build_seed_products())
    )
    agent = SearchAgentFactory(
        model=model,
        catalog_search=catalog_search,
        knowledge_base=knowledge_base,  # type: ignore[arg-type]
    ).build()

    reply = await agent.reply(
        [
            UserMsg(
                name="commerce_concierge",
                content="告诉我登机箱应该怎么挑。",
            )
        ]
    )

    assert knowledge_base.calls == [
        {
            "queries": ["登机箱应该怎么挑"],
            "top_k": 2,
        }
    ]
    assert len(model.calls) == 2

    available_tools = {
        tool["function"]["name"]
        for tool in model.calls[0]["tools"]
    }
    assert available_tools == {
        "product_search_tool",
        "category_insight_tool",
    }

    tool_results = collect_tool_result_texts(
        model.calls[1]["messages"]
    )
    assert any(
        "travel-gear.md" in text
        and "航空公司的尺寸限制" in text
        and '"score": 0.9133' in text
        for text in tool_results
    )
    assert reply.get_text_content() == (
        "挑选登机箱时，先核对航司尺寸限制，"
        "再比较箱体自重和轮组耐用性。"
    )
