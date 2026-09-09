from pathlib import Path

import pytest

from agentscope.credential import OpenAICredential
from agentscope.embedding import (
    EmbeddingModelBase,
    EmbeddingResponse,
)
from agentscope.rag import KnowledgeBase, QdrantStore

from app.infrastructure.rag.category_knowledge import (
    bootstrap_category_knowledge,
)


_TERMS = (
    "行李箱",
    "背包",
    "茶具",
    "免税额度",
)


class RecordingAxisEmbedding(
    EmbeddingModelBase[str],
):
    """Deterministic test embedding with observable API calls."""

    def __init__(self) -> None:
        super().__init__(
            credential=OpenAICredential(
                api_key="test-key",
            ),
            model="recording-axis-embedding",
            dimensions=len(_TERMS),
            parameters=None,
            context_size=8192,
            batch_size=16,
            max_retries=0,
            retry_delay=0.0,
        )
        self.calls: list[list[str]] = []

    async def _call_api(
        self,
        inputs: list[str],
        **kwargs,
    ) -> EmbeddingResponse:
        self.calls.append(list(inputs))

        return EmbeddingResponse(
            embeddings=[
                [
                    1.0 if term in text else 0.0
                    for term in _TERMS
                ]
                for text in inputs
            ],
        )


def write_test_documents(directory: Path) -> None:
    directory.mkdir()
    (directory / "travel.md").write_text(
        "# 旅行装备\n"
        "行李箱需要检查尺寸和自重。"
        "折叠背包需要检查容量和背负系统。",
        encoding="utf-8",
    )
    (directory / "home.md").write_text(
        "# 家居生活\n"
        "茶具需要检查材质和食品接触安全标准。",
        encoding="utf-8",
    )


def build_test_knowledge_base(
    embedding: RecordingAxisEmbedding,
    store: QdrantStore,
) -> KnowledgeBase:
    return KnowledgeBase(
        name="category_insight_test",
        description="测试用品类知识库",
        embedding_model=embedding,
        vector_store=store,
        collection="test_category_knowledge",
    )


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent(
    tmp_path: Path,
) -> None:
    documents = tmp_path / "knowledge"
    write_test_documents(documents)

    embedding = RecordingAxisEmbedding()
    store = QdrantStore(location=":memory:")
    knowledge_base = build_test_knowledge_base(
        embedding,
        store,
    )

    async with store:
        inserted = await bootstrap_category_knowledge(
            knowledge_base,
            knowledge_dir=documents,
        )

        assert inserted == 2
        assert len(await knowledge_base.list_documents()) == 2

        first_bootstrap_calls = len(embedding.calls)
        assert first_bootstrap_calls == 2

        inserted_again = await bootstrap_category_knowledge(
            knowledge_base,
            knowledge_dir=documents,
        )

        assert inserted_again == 0
        assert len(embedding.calls) == first_bootstrap_calls


@pytest.mark.asyncio
async def test_search_embeds_query_and_returns_relevant_chunk(
    tmp_path: Path,
) -> None:
    documents = tmp_path / "knowledge"
    write_test_documents(documents)

    embedding = RecordingAxisEmbedding()
    store = QdrantStore(location=":memory:")
    knowledge_base = build_test_knowledge_base(
        embedding,
        store,
    )

    async with store:
        await bootstrap_category_knowledge(
            knowledge_base,
            knowledge_dir=documents,
        )
        embedding.calls.clear()

        results = await knowledge_base.search(
            queries=["行李箱应该怎么挑"],
            top_k=1,
        )

        assert embedding.calls == [
            ["行李箱应该怎么挑"],
        ]
        assert len(results) == 1
        assert "行李箱" in results[0].chunk.content.text
        assert results[0].chunk.metadata["source"] == (
            "travel.md"
        )


@pytest.mark.asyncio
async def test_bootstrap_degrades_when_store_is_unavailable(
    tmp_path: Path,
) -> None:
    class BrokenKnowledgeBase:
        async def ensure_collection(self) -> None:
            raise RuntimeError("向量库连接失败")

    result = await bootstrap_category_knowledge(
        BrokenKnowledgeBase(),  # type: ignore[arg-type]
        knowledge_dir=tmp_path,
    )

    assert result == 0
