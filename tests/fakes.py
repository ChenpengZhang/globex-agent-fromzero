from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.tool import ToolChoice


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
