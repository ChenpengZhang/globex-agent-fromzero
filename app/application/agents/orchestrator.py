from dataclasses import dataclass

from app.application.agents.session_registry import (
    SessionRegistry,
)

from agentscope.message import UserMsg


@dataclass(frozen=True)
class SubmitIntentInput:
    shopping_session_id: str
    buyer_id: str
    locale: str
    currency: str
    raw_query: str

    def __post_init__(self) -> None:
        if not self.shopping_session_id.strip():
            raise ValueError(
                "shopping_session_id 不能为空",
            )

        if not self.buyer_id.strip():
            raise ValueError("buyer_id 不能为空")

        if not self.raw_query.strip():
            raise ValueError("raw_query 不能为空")

        normalized_currency = self.currency.strip().upper()
        if len(normalized_currency) != 3:
            raise ValueError(
                "currency 必须是三位币种代码",
            )

        object.__setattr__(
            self,
            "shopping_session_id",
            self.shopping_session_id.strip(),
        )
        object.__setattr__(
            self,
            "buyer_id",
            self.buyer_id.strip(),
        )
        object.__setattr__(
            self,
            "locale",
            self.locale.strip() or "zh-CN",
        )
        object.__setattr__(
            self,
            "currency",
            normalized_currency,
        )
        object.__setattr__(
            self,
            "raw_query",
            self.raw_query.strip(),
        )


@dataclass(frozen=True)
class SubmitIntentOutput:
    shopping_session_id: str
    final_text: str


class MainAgentOrchestrator:
    def __init__(
        self,
        sessions: SessionRegistry
    ) -> None:
        self._sessions = sessions

    async def handle_intent(
        self,
        intent: SubmitIntentInput,
    ) -> SubmitIntentOutput:
        session = await self._sessions.get_or_create(
            shopping_session_id=(
                intent.shopping_session_id
            ),
            buyer_id=intent.buyer_id,
        )

        message_content = (
            "<shopping-context>\n"
            f"locale: {intent.locale}\n"
            f"currency: {intent.currency}\n"
            "</shopping-context>\n\n"
            f"{intent.raw_query}"
        )

        user_message = UserMsg(
            name=intent.buyer_id,
            content=message_content,
        )

        async with session.execution_lock:
            reply = await session.agent.reply(
                [user_message],
            )
        # avoid two replies using the same session

        return SubmitIntentOutput(
            shopping_session_id=(
                intent.shopping_session_id
            ),
            final_text=reply.get_text_content() or "",
        )
    