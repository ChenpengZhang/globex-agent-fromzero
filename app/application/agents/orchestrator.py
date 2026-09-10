import asyncio
import logging
import time

from dataclasses import dataclass
from agentscope.agent import Agent
from agentscope.event import TextBlockDeltaEvent
from agentscope.message import Msg, UserMsg

from app.domain.session.ports.conversation_store import (
    ConversationEventRecord,
    ConversationStore,
    ConversationTurn,
)

from app.application.events import (
    EventBus,
    TradeEvent,
    TradeEventType,
)
from app.application.agents.session_registry import (
    SessionRegistry,
)

from app.infrastructure.context import (
    ShoppingContext,
    ShoppingContextSnapshot,
)


logger = logging.getLogger(__name__)


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
        event_bus: EventBus,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._sessions = sessions
        self._event_bus = event_bus
        self._conversation_store = conversation_store

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
            started_at = time.monotonic()
            final_text: str | None = None

            trace = (
                self._event_bus.subscribe(
                    intent.shopping_session_id,
                )
                if self._conversation_store is not None
                else None
            )
            # Subscribe to record trace info (for logging and analizing).
            # Note that subcription occurs after the session lock
            # in order to avoid B to collect A's trace.

            try:
                final_text = await self._consume_reply(
                    agent = session.agent,
                    user_message = user_message,
                    shopping_session_id =(
                        intent.shopping_session_id
                    ),
                )

                self._event_bus.publish(
                    intent.shopping_session_id,
                    TradeEventType.FINAL_RESULT,
                    {
                        "text": final_text,
                    },
                )

            except Exception as error:
                self._event_bus.publish(
                    intent.shopping_session_id,
                    TradeEventType.ERROR,
                    {
                        "message": str(error),
                    },
                )
                raise

            finally:
                await self._sessions.persist(
                    intent.shopping_session_id,
                )
                # Persist AgentState on both success and failure

                await self._record_conversation(
                    intent=intent,
                    final_text=final_text,
                    latency_ms=int(
                        (time.monotonic() - started_at) * 1000
                    ),
                    trace=trace,
                )
                # save conversation and trace

                ShoppingContext.reset(reset_token)


        return SubmitIntentOutput(
            shopping_session_id=(
                intent.shopping_session_id
            ),
            final_text=final_text or "",
        )

    async def _record_conversation(
        self,
        intent: SubmitIntentInput,
        final_text: str | None,
        latency_ms: int,
        trace: asyncio.Queue[TradeEvent] | None,
    ) -> None:
        """Persist readable turns and non-token execution events."""

        if self._conversation_store is None:
            return

        events: list[ConversationEventRecord] = []

        if trace is not None:
            self._event_bus.unsubscribe(
                intent.shopping_session_id,
                trace,
            )
            # trace is temporary

            while not trace.empty():
                event = trace.get_nowait()

                if event.type is TradeEventType.TOKEN_DELTA:
                    continue

                events.append(
                    ConversationEventRecord(
                        session_id=(
                            intent.shopping_session_id
                        ),
                        type=event.type.value,
                        payload=event.payload,
                        occurred_at=(
                            event.occurred_at.isoformat()
                        ),
                    )
                )

        try:
            await self._conversation_store.touch_session(
                session_id=intent.shopping_session_id,
                buyer_id=intent.buyer_id,
                locale=intent.locale,
                currency=intent.currency,
            )

            await self._conversation_store.append_turn(
                ConversationTurn(
                    session_id=intent.shopping_session_id,
                    buyer_id=intent.buyer_id,
                    role="buyer",
                    content=intent.raw_query,
                )
            )

            if final_text is not None:
                await self._conversation_store.append_turn(
                    ConversationTurn(
                        session_id=(
                            intent.shopping_session_id
                        ),
                        buyer_id=intent.buyer_id,
                        role="agent",
                        content=final_text,
                        latency_ms=latency_ms,
                    )
                )

            await self._conversation_store.append_events(
                events,
            )

        except Exception as error:
            logger.warning(
                "Failed to persist conversation %s: %s",
                intent.shopping_session_id,
                error,
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
                    self._event_bus.publish(
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
    