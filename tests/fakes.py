from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.tool import ToolChoice


def build_composition_settings(
    *,
    reranker_base_url: str = "",
) -> SimpleNamespace:
    """Small settings double for fully monkeypatched composition tests."""
    return SimpleNamespace(
        reranker_base_url=reranker_base_url,
    )


class RecordingVectorStore:
    """Minimal async lifecycle double for a vector store."""

    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.exit_count += 1


class EmptyKnowledgeBase:
    """KnowledgeBase test double with lifecycle and no search hits."""

    def __init__(self) -> None:
        self.vector_store = RecordingVectorStore()
        self.document_ids: list[str] = []
        self.ensure_collection_count = 0

    async def ensure_collection(self) -> None:
        self.ensure_collection_count += 1

    async def list_documents(self) -> list:
        return [
            SimpleNamespace(document_id=document_id)
            for document_id in self.document_ids
        ]

    async def insert_document(
        self,
        *,
        chunks,
        document_id: str,
        document_metadata: dict,
    ) -> str:
        self.document_ids.append(document_id)
        return document_id

    async def search(
        self,
        queries: list[str],
        top_k: int = 5,
    ) -> list:
        return []


class DeterministicEmbeddingClient:
    """Offline embedding port double with observable calls."""

    def __init__(self) -> None:
        self.embed_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    async def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return [1.0, 0.0]

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts]


class RecordingProductVectorIndex:
    """Offline product-index double with lifecycle observations."""

    def __init__(self) -> None:
        self.ready_dimensions: list[int] = []
        self.upsert_calls: list[dict] = []
        self.search_calls: list[dict] = []
        self.close_count = 0

    async def ensure_ready(self, vector_dim: int) -> None:
        self.ready_dimensions.append(vector_dim)

    async def upsert_products(
        self,
        products,
        embeddings: list[list[float]],
    ) -> None:
        self.upsert_calls.append(
            {
                "products": list(products),
                "embeddings": list(embeddings),
            }
        )

    async def search(
        self,
        embedding: list[float],
        top_n: int,
    ) -> list:
        self.search_calls.append(
            {
                "embedding": embedding,
                "top_n": top_n,
            }
        )
        return []

    async def close(self) -> None:
        self.close_count += 1


class ScriptedChatModel(ChatModelBase):
    """Return predefined model responses without network access."""

    class Parameters(BaseModel):
        pass

    def __init__(
        self,
        responses: list[ChatResponse],
    ) -> None:
        super().__init__(
            credential=CredentialBase(),
            model="scripted-test-model",
            parameters=self.Parameters(),
            stream=False,
            max_retries=0,
        )

        self.formatter = OpenAIChatFormatter()
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.calls.append(
            {
                "model_name": model_name,
                "messages": deepcopy(messages),
                "tools": deepcopy(tools),
                "tool_choice": tool_choice,
            },
        )

        if not self._responses:
            raise AssertionError(
                "ScriptedChatModel 没有更多预设响应",
            )

        return self._responses.pop(0)
