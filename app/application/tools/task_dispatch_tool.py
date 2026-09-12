import logging

from typing import Literal

from agentscope.message import (
    TextBlock,
    ToolResultState,
    UserMsg,
)
from agentscope.tool import ToolChunk

from app.application.memory.preference_selector import (
    PreferenceSelector,
    render_preference_hint,
)
from app.domain.buyer.ports.preference_store import (
    PreferenceStore,
)
from app.infrastructure.context import ShoppingContext
from app.application.agents.search_agent import (
    SearchAgentFactory,
)
from app.application.agents.trade_agent import (
    TradeAgentFactory,
)


logger = logging.getLogger(__name__)


def build_task_dispatch_tool(
    search_factory: SearchAgentFactory,
    trade_factory: TradeAgentFactory,
    preference_store: PreferenceStore | None = None,
    preference_selector: PreferenceSelector | None = None,
    preference_top_k: int = 5,
    inject_preferences: bool = True,
):
    selector = (
        preference_selector
        or PreferenceSelector()
    )
    async def _preference_hint(
        subagent_type: str,
        demands: str,
    ) -> str | None:
        if (
            not inject_preferences
            or preference_store is None
            or subagent_type != "search_agent"
        ):
            return None

        context = ShoppingContext.current()

        if context is None:
            return None

        try:
            preferences = (
                await preference_store.list_by_buyer(
                    context.buyer_id,
                )
            )
            selected = await selector.select(
                preferences=preferences,
                query=demands,
                top_k=preference_top_k,
            )
        except Exception as error:
            logger.warning(
                "SearchAgent preference injection failed; "
                "continuing without memory: %s",
                error,
            )
            return None

        if not selected:
            return None

        return render_preference_hint(
            selected,
        )

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
                A self-contained task containing all required business
                details. Buyer preferences are injected by the server
                when dispatching SearchAgent.
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

        worker_inputs = [
            UserMsg(
                name="commerce_concierge",
                content=normalized_demands,
            ),
        ]

        preference_hint = await _preference_hint(
            subagent_type=subagent_type,
            demands=normalized_demands,
        )

        if preference_hint is not None:
            worker_inputs.insert(
                0,
                UserMsg(
                    name="memory_hint",
                    content=preference_hint,
                ),
            )

        reply = await worker.reply(
            worker_inputs,
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
