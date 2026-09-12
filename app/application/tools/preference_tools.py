from typing import Literal

from agentscope.message import (
    TextBlock,
    ToolResultState,
)
from agentscope.tool import ToolChunk

from app.application.events import (
    EventPublisher,
    TradeEventType,
)
from app.domain.buyer.preference import BuyerPreference
from app.domain.buyer.ports.preference_store import (
    PreferenceStore,
)
from app.infrastructure.context import ShoppingContext


def _result(
    text: str,
    state: ToolResultState,
) -> ToolChunk:
    return ToolChunk(
        content=[
            TextBlock(
                type="text",
                text=text,
            ),
        ],
        state=state,
    )


def build_remember_preference_tool(
    store: PreferenceStore,
    event_publisher: EventPublisher,
):
    async def remember_preference_tool(
        kind: Literal["like", "dislike"],
        statement: str,
    ) -> ToolChunk:
        """Remember one stable buyer preference across conversations.

        Use this only for durable preferences such as material
        restrictions, style preferences, or recurring shopping habits.
        Do not store one-time requirements for the current purchase.

        Args:
            kind (`str`):
                "like" for a positive preference or "dislike"
                for a restriction or blacklist.
            statement (`str`):
                A short standalone preference statement.
        """
        try:
            context = ShoppingContext.require_current()
        except RuntimeError as error:
            return _result(
                f"[error] {error}",
                ToolResultState.ERROR,
            )

        event_publisher.publish(
            context.shopping_session_id,
            TradeEventType.TOOL_INVOKE,
            {
                "tool": "remember_preference_tool",
                "args": {
                    "kind": kind,
                    "statement": statement,
                },
            },
        )

        try:
            preference = BuyerPreference(
                buyer_id=context.buyer_id,
                kind=kind,
                statement=statement,
            )
            await store.append(preference)
        except Exception as error:
            event_publisher.publish(
                context.shopping_session_id,
                TradeEventType.TOOL_RESULT,
                {
                    "tool": "remember_preference_tool",
                    "error": str(error),
                },
            )
            return _result(
                f"[error] 保存买家偏好失败：{error}",
                ToolResultState.ERROR,
            )

        event_publisher.publish(
            context.shopping_session_id,
            TradeEventType.TOOL_RESULT,
            {
                "tool": "remember_preference_tool",
                "saved": preference.statement,
                "kind": preference.kind,
            },
        )

        return _result(
            (
                "已记住买家偏好："
                f"[{preference.kind}] "
                f"{preference.statement}"
            ),
            ToolResultState.SUCCESS,
        )

    return remember_preference_tool


def build_forget_preference_tool(
    store: PreferenceStore,
    event_publisher: EventPublisher,
):
    async def forget_preference_tool(
        statement: str,
    ) -> ToolChunk:
        """Forget one previously stored buyer preference.

        Use this only when the buyer explicitly withdraws a durable
        preference. The statement must exactly match one of the
        stored preference statements.

        Args:
            statement (`str`):
                Exact preference statement to remove.
        """
        try:
            context = ShoppingContext.require_current()
        except RuntimeError as error:
            return _result(
                f"[error] {error}",
                ToolResultState.ERROR,
            )

        normalized_statement = statement.strip()

        event_publisher.publish(
            context.shopping_session_id,
            TradeEventType.TOOL_INVOKE,
            {
                "tool": "forget_preference_tool",
                "args": {
                    "statement": normalized_statement,
                },
            },
        )

        if not normalized_statement:
            error = "preference statement cannot be empty"

            event_publisher.publish(
                context.shopping_session_id,
                TradeEventType.TOOL_RESULT,
                {
                    "tool": "forget_preference_tool",
                    "error": error,
                },
            )

            return _result(
                f"[error] {error}",
                ToolResultState.ERROR,
            )

        try:
            deleted = await store.delete(
                context.buyer_id,
                normalized_statement,
            )

            if not deleted:
                remaining = await store.list_by_buyer(
                    context.buyer_id,
                )
        except Exception as error:
            event_publisher.publish(
                context.shopping_session_id,
                TradeEventType.TOOL_RESULT,
                {
                    "tool": "forget_preference_tool",
                    "error": str(error),
                },
            )

            return _result(
                f"[error] 撤回买家偏好失败：{error}",
                ToolResultState.ERROR,
            )

        if deleted:
            event_publisher.publish(
                context.shopping_session_id,
                TradeEventType.TOOL_RESULT,
                {
                    "tool": "forget_preference_tool",
                    "deleted": normalized_statement,
                },
            )

            return _result(
                (
                    "已撤回买家偏好："
                    f"{normalized_statement}"
                ),
                ToolResultState.SUCCESS,
            )

        listing = (
            "\n".join(
                (
                    f"- [{preference.kind}] "
                    f"{preference.statement}"
                )
                for preference in remaining
            )
            if remaining
            else "（当前没有长期偏好）"
        )

        event_publisher.publish(
            context.shopping_session_id,
            TradeEventType.TOOL_RESULT,
            {
                "tool": "forget_preference_tool",
                "not_found": normalized_statement,
                "remaining": len(remaining),
            },
        )

        return _result(
            (
                f"未找到偏好「{normalized_statement}」，"
                "没有删除任何内容。"
                "如需撤回，请使用以下偏好的原文：\n"
                f"{listing}"
            ),
            ToolResultState.SUCCESS,
        )
        # Still return success even if not found.
        # But will teach the model what to delete.

    return forget_preference_tool
