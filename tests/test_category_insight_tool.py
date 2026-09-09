import json

import pytest

from agentscope.message import TextBlock, ToolResultState
from agentscope.rag import Chunk
from agentscope.rag._vdb import VectorSearchResult
from agentscope.tool import FunctionTool

from app.application.tools.category_insight_tool import (
    _chunk_text,
    build_category_insight_tool,
)


class RecordingKnowledgeBase:
    def __init__(
        self,
        results: list[VectorSearchResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.results = results or []
        self.error = error
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

        if self.error is not None:
            raise self.error

        return self.results


def make_result(
    *,
    text: str,
    score: float,
    document_id: str,
    metadata: dict | None = None,
) -> VectorSearchResult:
    return VectorSearchResult(
        score=score,
        document_id=document_id,
        chunk=Chunk(
            content=TextBlock(
                type="text",
                text=text,
            ),
            source=f"{document_id}.md",
            chunk_index=0,
            total_chunks=1,
            metadata=metadata or {},
        ),
    )


def test_category_insight_tool_generates_expected_schema() -> None:
    knowledge_base = RecordingKnowledgeBase()
    function_tool = FunctionTool(
        build_category_insight_tool(
            knowledge_base,  # type: ignore[arg-type]
        ),
        is_read_only=True,
    )

    assert function_tool.name == "category_insight_tool"
    assert function_tool.input_schema["required"] == [
        "question",
    ]
    assert function_tool.input_schema["properties"][
        "top_k"
    ]["default"] == 3


@pytest.mark.asyncio
async def test_category_insight_returns_content_source_and_score(
) -> None:
    knowledge_base = RecordingKnowledgeBase(
        results=[
            make_result(
                text="登机箱需要核对尺寸和自重。",
                score=0.876543,
                document_id="travel-gear",
                metadata={
                    "source": "travel-gear.md",
                },
            ),
            make_result(
                text="跨境购买还需关注到手价。",
                score=0.712345,
                document_id="cross-border-guide",
            ),
        ]
    )
    tool = build_category_insight_tool(
        knowledge_base,  # type: ignore[arg-type]
    )

    result = await tool(
        question="  旅行装备应该怎么挑  ",
        top_k=2,
    )

    assert result.state == ToolResultState.SUCCESS
    assert knowledge_base.calls == [
        {
            "queries": ["旅行装备应该怎么挑"],
            "top_k": 2,
        }
    ]

    payload = json.loads(result.content[0].text)
    assert payload == {
        "insights": [
            {
                "content": "登机箱需要核对尺寸和自重。",
                "source": "travel-gear.md",
                "score": 0.8765,
            },
            {
                "content": "跨境购买还需关注到手价。",
                "source": "cross-border-guide",
                "score": 0.7123,
            },
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "top_k", "expected_error"),
    [
        ("   ", 3, "[error] question 不能为空"),
        ("旅行装备怎么挑", 0, "[error] top_k 必须是正整数"),
        ("旅行装备怎么挑", -1, "[error] top_k 必须是正整数"),
    ],
)
async def test_category_insight_rejects_invalid_input(
    question: str,
    top_k: int,
    expected_error: str,
) -> None:
    knowledge_base = RecordingKnowledgeBase()
    tool = build_category_insight_tool(
        knowledge_base,  # type: ignore[arg-type]
    )

    result = await tool(
        question=question,
        top_k=top_k,
    )

    assert result.state == ToolResultState.ERROR
    assert result.content[0].text == expected_error
    assert not knowledge_base.calls


@pytest.mark.asyncio
async def test_category_insight_reports_knowledge_failure() -> None:
    knowledge_base = RecordingKnowledgeBase(
        error=RuntimeError("向量库连接失败"),
    )
    tool = build_category_insight_tool(
        knowledge_base,  # type: ignore[arg-type]
    )

    result = await tool(
        question="旅行装备怎么挑",
    )

    assert result.state == ToolResultState.ERROR
    assert result.content[0].text == (
        "[error] 品类知识库不可用：向量库连接失败"
    )


def test_chunk_text_normalizes_supported_shapes() -> None:
    assert _chunk_text("plain text") == "plain text"
    assert _chunk_text(
        TextBlock(type="text", text="block text")
    ) == "block text"
    assert _chunk_text(
        {"text": "mapping text"}
    ) == "mapping text"
