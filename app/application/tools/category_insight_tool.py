import json

from agentscope.message import (
    TextBlock,
    ToolResultState,
)
from agentscope.rag import KnowledgeBase
from agentscope.tool import ToolChunk


def _chunk_text(content) -> str:
    """Convert different chunk content shapes to serializable text."""
    if isinstance(content, str):
        return content

    text = getattr(content, "text", None)

    if text is not None:
        return text

    if isinstance(content, dict):
        return content.get("text") or str(content)

    return str(content)


def build_category_insight_tool(
    knowledge_base: KnowledgeBase,
):
    async def category_insight_tool(
        question: str,
        top_k: int = 3,
    ) -> ToolChunk:
        """Retrieve category knowledge for shopping guidance.

        Use this tool for questions about how to choose a product,
        important attributes, common pitfalls, and reference price
        ranges. It returns knowledge, not purchasable products.
        Use product_search_tool when concrete products are required.

        Args:
            question (`str`):
                A self-contained category question, such as
                "旅行装备应该关注哪些材质和耐用性指标".
            top_k (`int`):
                Maximum number of relevant knowledge chunks.
        """
        normalized_question = question.strip()

        if not normalized_question:
            return ToolChunk(
                content=[
                    TextBlock(
                        type="text",
                        text="[error] question 不能为空",
                    ),
                ],
                state=ToolResultState.ERROR,
            )

        if top_k <= 0:
            return ToolChunk(
                content=[
                    TextBlock(
                        type="text",
                        text="[error] top_k 必须是正整数",
                    ),
                ],
                state=ToolResultState.ERROR,
            )

        try:
            results = await knowledge_base.search(
                queries=[normalized_question],
                top_k=top_k,
            )

        except Exception as error:
            return ToolChunk(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "[error] 品类知识库不可用："
                            f"{error}"
                        ),
                    ),
                ],
                state=ToolResultState.ERROR,
            )

        insights = [
            {
                "content": _chunk_text(
                    result.chunk.content
                ),
                "source": (
                    result.chunk.metadata.get(
                        "source",
                        result.document_id,
                    )
                    if result.chunk.metadata
                    else result.document_id
                ),
                "score": round(
                    result.score,
                    4,
                ),
            }
            for result in results
        ]

        return ToolChunk(
            content=[
                TextBlock(
                    type="text",
                    text=json.dumps(
                        {
                            "insights": insights,
                        },
                        ensure_ascii=False,
                    ),
                ),
            ],
            state=ToolResultState.SUCCESS,
        )

    return category_insight_tool
