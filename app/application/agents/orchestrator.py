from dataclasses import dataclass
from agentscope.agent import Agent
from agentscope.event import TextBlockDeltaEvent
from agentscope.message import Msg, UserMsg

from app.application.events import (
    EventPublisher,
    TradeEventType,
)
from app.application.agents.session_registry import (
    SessionRegistry,
)

from app.infrastructure.context import (
    ShoppingContext,
    ShoppingContextSnapshot,
)


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
        sessions: SessionRegistry,
        event_publisher: EventPublisher,
    ) -> None:
        self._sessions = sessions
        self._event_publisher = event_publisher

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

        snapshot = ShoppingContextSnapshot(
            shopping_session_id=(
                intent.shopping_session_id
            ),
            buyer_id=intent.buyer_id,
            locale=intent.locale,
            currency=intent.currency,
        )

        async with session.execution_lock:
            # avoid two replies using the same session
            reset_token = ShoppingContext.set(snapshot)
            # This token is used to recover ContextVar
            # incase of recursive calls clears out all contexts
            # make sure use the token to clear the ShoppingContext

            try:
                final_text = await self._consume_reply(
                    agent = session.agent,
                    user_message = user_message,
                    shopping_session_id =(
                        intent.shopping_session_id
                    ),
                )

                self._event_publisher.publish(
                    intent.shopping_session_id,
                    TradeEventType.FINAL_RESULT,
                    {
                        "text": final_text,
                    },
                )

            except Exception as error:
                self._event_publisher.publish(
                    intent.shopping_session_id,
                    TradeEventType.ERROR,
                    {
                        "message": str(error),
                    },
                )
                raise

            finally:
                ShoppingContext.reset(reset_token)


        return SubmitIntentOutput(
            shopping_session_id=(
                intent.shopping_session_id
            ),
            final_text=final_text,
        )

    async def _consume_reply(
        self,
        agent: Agent,
        user_message: UserMsg,
        shopping_session_id: str,
    ) -> str:
        final_text = ""

        async for event in agent.reply_stream(
            [user_message],
            yield_final_msg=True,
        ):
            if isinstance(event, TextBlockDeltaEvent):
                if event.delta:
                    self._event_publisher.publish(
                        shopping_session_id,
                        TradeEventType.TOKEN_DELTA,
                        {
                            "agent_name": agent.name,
                            "token": event.delta,
                        },
                    )

            elif isinstance(event, Msg):
                final_text = (
                    event.get_text_content() or ""
                )

        return final_text
    