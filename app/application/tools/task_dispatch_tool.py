from typing import Literal

from agentscope.message import (
    TextBlock,
    ToolResultState,
    UserMsg,
)
from agentscope.tool import ToolChunk

from app.application.agents.search_agent import (
    SearchAgentFactory,
)
from app.application.agents.trade_agent import (
    TradeAgentFactory,
)


def build_task_dispatch_tool(
    search_factory: SearchAgentFactory,
    trade_factory: TradeAgentFactory,
):
    async def task_dispatch(
        subagent_type: Literal[
            "search_agent",
            "trade_agent",
        ],
        demands: str,
    ) -> ToolChunk:
        """Dispatch a self-contained task to a specialist Agent.

        Use this tool only when a task benefits from specialist
        context isolation or requires a deeper tool-calling chain.
        The specialist cannot see the MainAgent conversation history.

        Args:
            subagent_type (`str`):
                Specialist type: search_agent or trade_agent.
            demands (`str`):
                A self-contained task containing every detail
                required by the specialist.
        """
        normalized_demands = demands.strip()

        if not normalized_demands:
            return ToolChunk(
                content=[
                    TextBlock(
                        type="text",
                        text="[error] demands 不能为空",
                    ),
                ],
                state=ToolResultState.ERROR,
            )

        if subagent_type == "search_agent":
            worker = search_factory.build()
        elif subagent_type == "trade_agent":
            worker = trade_factory.build()
        else:
            return ToolChunk(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "[error] 未知 subagent_type："
                            f"{subagent_type}"
                        ),
                    ),
                ],
                state=ToolResultState.ERROR,
            )

        reply = await worker.reply(
            [
                UserMsg(
                    name="commerce_concierge",
                    content=normalized_demands,
                ),
            ]
        )

        return ToolChunk(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        reply.get_text_content()
                        or ""
                    ),
                ),
            ],
            state=ToolResultState.SUCCESS,
        )

    return task_dispatch
