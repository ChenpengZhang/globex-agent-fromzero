from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.tool import ToolChoice


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