import asyncio

import pytest

from agentscope.message import TextBlock
from agentscope.model import ChatResponse

from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import (
    MainAgentOrchestrator,
    SubmitIntentInput,
)
from app.application.agents.session_registry import SessionRegistry
from app.infrastructure.context import (
    ShoppingContext,
    ShoppingContextSnapshot,
)
from tests.fakes import ScriptedChatModel


class ContextCapturingChatModel(ScriptedChatModel):
    def __init__(self) -> None:
        super().__init__(
            responses=[
                ChatResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text="上下文已读取",
                        )
                    ],
                    is_last=True,
                )
            ]
        )
        self.captured_context: ShoppingContextSnapshot | None = None

    async def _call_api(self, *args, **kwargs) -> ChatResponse:
        self.captured_context = ShoppingContext.require_current()
        return await super()._call_api(*args, **kwargs)


def make_snapshot(
    session_id: str,
    buyer_id: str,
) -> ShoppingContextSnapshot:
    return ShoppingContextSnapshot(
        shopping_session_id=session_id,
        buyer_id=buyer_id,
        locale="zh-CN",
        currency="CNY",
    )


def test_require_current_rejects_missing_request_context() -> None:
    assert ShoppingContext.current() is None

    with pytest.raises(RuntimeError, match="缺少 ShoppingContext"):
        ShoppingContext.require_current()


def test_reset_restores_previous_nested_context() -> None:
    outer = make_snapshot("session-outer", "buyer-outer")
    inner = make_snapshot("session-inner", "buyer-inner")
    outer_token = ShoppingContext.set(outer)

    try:
        inner_token = ShoppingContext.set(inner)
        assert ShoppingContext.current() is inner

        ShoppingContext.reset(inner_token)
        assert ShoppingContext.current() is outer
    finally:
        ShoppingContext.reset(outer_token)

    assert ShoppingContext.current() is None


@pytest.mark.asyncio
async def test_context_is_isolated_between_concurrent_tasks() -> None:
    async def read_after_yield(
        snapshot: ShoppingContextSnapshot,
    ) -> ShoppingContextSnapshot:
        reset_token = ShoppingContext.set(snapshot)
        try:
            await asyncio.sleep(0)
            return ShoppingContext.require_current()
        finally:
            ShoppingContext.reset(reset_token)

    first, second = await asyncio.gather(
        read_after_yield(
            make_snapshot("session-a", "buyer-a")
        ),
        read_after_yield(
            make_snapshot("session-b", "buyer-b")
        ),
    )

    assert first.buyer_id == "buyer-a"
    assert second.buyer_id == "buyer-b"
    assert ShoppingContext.current() is None


@pytest.mark.asyncio
async def test_orchestrator_exposes_context_only_during_agent_reply() -> None:
    model = ContextCapturingChatModel()
    factory = MainAgentFactory(model=model, tools=[])
    orchestrator = MainAgentOrchestrator(
        SessionRegistry(factory)
    )

    result = await orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-001",
            buyer_id="buyer-001",
            locale="zh-CN",
            currency="CNY",
            raw_query="你好",
        )
    )

    assert result.final_text == "上下文已读取"
    assert model.captured_context == ShoppingContextSnapshot(
        shopping_session_id="session-001",
        buyer_id="buyer-001",
        locale="zh-CN",
        currency="CNY",
    )
    assert ShoppingContext.current() is None
