import asyncio
import hashlib
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
from app.application.memory.preference_selector import (
    PreferenceSelector,
    render_preference_hint,
    render_preference_lines,
)
from app.domain.buyer.ports.preference_store import (
    PreferenceStore,
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
from app.infrastructure.cache.semantic_cache import (
    SemanticCache,
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
        semantic_cache: SemanticCache | None = None,
        preference_store: PreferenceStore | None = None,
        preference_selector: PreferenceSelector | None = None,
        preference_top_k: int = 5,
    ) -> None:
        self._sessions = sessions
        self._event_bus = event_bus
        self._conversation_store = conversation_store
        self._semantic_cache = semantic_cache
        self._preference_store = preference_store
        self._preference_selector = (
            preference_selector
            or PreferenceSelector()
        )
        self._preference_top_k = preference_top_k
        self._injected_preferences: dict[str, str] = {}

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
                has_history = await self._has_history(
                    agent=session.agent,
                    shopping_session_id=(
                        intent.shopping_session_id
                    ),
                )

                cached_reply = await self._lookup_cache(
                    intent=intent,
                    has_history=has_history,
                )

                if cached_reply is not None:
                    final_text = cached_reply
                else:
                    agent_inputs = await self._build_agent_inputs(
                        intent=intent,
                        user_message=user_message,
                    )

                    final_text = await self._consume_reply(
                        agent=session.agent,
                        messages=agent_inputs,
                        shopping_session_id=(
                            intent.shopping_session_id
                        ),
                    )

                    await self._remember_cache(
                        intent=intent,
                        reply=final_text,
                        has_history=has_history,
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

    async def _has_history(
        self,
        agent: Agent,
        shopping_session_id: str,
    ) -> bool:
        """
        Decide whether semantic cache reuse is safe for this session.

        Persistent conversation history is authoritative because a
        previous cache hit does not add messages to AgentState.
        """

        if self._conversation_store is None:
            return bool(agent.state.context)

        try:
            turns = await self._conversation_store.list_turns(
                shopping_session_id,
                limit=1,
            )  # request the conversation storage, e.g. sql.
        except Exception as error:
            logger.warning(
                "Conversation history lookup failed; "
                "semantic cache is disabled for this turn: %s",
                error,
            )
            return True

        return bool(
            turns
            or agent.state.context
        )

    async def _preference_scope(
        self,
        buyer_id: str,
    ) -> str | None:
        """
        Fingerprint the buyer's complete durable preference state.

        None means the preference state could not be read safely.
        An empty string means the buyer currently has no preferences.
        """

        if self._preference_store is None:
            return ""

        try:
            preferences = (
                await self._preference_store.list_by_buyer(
                    buyer_id,
                )
            )
        except Exception as error:
            logger.warning(
                "Preference fingerprint lookup failed; "
                "semantic cache is disabled for this turn: %s",
                error,
            )
            return None

        if not preferences:
            return ""

        rendered = render_preference_lines(
            preferences
        )

        return hashlib.sha256(
            rendered.encode("utf-8")
        ).hexdigest()[:16]

    async def _lookup_cache(
        self,
        intent: SubmitIntentInput,
        has_history: bool,
    ) -> str | None:
        if self._semantic_cache is None:
            return None

        scope = await self._preference_scope(
            intent.buyer_id
        )

        if scope is None:
            return None

        try:
            hit = await self._semantic_cache.lookup(
                buyer_id=intent.buyer_id,
                query=intent.raw_query,
                has_history=has_history,
                scope=scope,
            )
        except Exception as error:
            logger.warning(
                "Semantic cache lookup failed; "
                "continuing with the Agent: %s",
                error,
            )
            return None

        if hit is None:
            return None

        logger.info(
            "Semantic cache hit with similarity %.4f",
            hit.similarity,
        )

        self._event_bus.publish(
            intent.shopping_session_id,
            TradeEventType.CACHE_HIT,
            {
                "similarity": hit.similarity,
                "matched_query": hit.matched_query,
            },
        )

        return hit.reply

    async def _remember_cache(
        self,
        intent: SubmitIntentInput,
        reply: str,
        has_history: bool,
    ) -> None:
        if self._semantic_cache is None:
            return

        scope = await self._preference_scope(
            intent.buyer_id
        )

        if scope is None:
            return

        try:
            await self._semantic_cache.remember(
                buyer_id=intent.buyer_id,
                query=intent.raw_query,
                reply=reply,
                has_history=has_history,
                scope=scope,
            )
        except Exception as error:
            logger.warning(
                "Semantic cache update failed; "
                "continuing without caching: %s",
                error,
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
                    content=intent.raw_query,  # only save raw query
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

    async def _build_agent_inputs(
        self,
        intent: SubmitIntentInput,
        user_message: UserMsg,
    ) -> list[Msg]:
        """Add relevant buyer preferences to the current turn."""

        if self._preference_store is None:
            return [user_message]

        try:
            preferences = (
                await self._preference_store.list_by_buyer(
                    intent.buyer_id,
                )
            )

            selected = (
                await self._preference_selector.select(
                    preferences=preferences,
                    query=intent.raw_query,
                    top_k=self._preference_top_k,
                )
            )
        except Exception as error:
            logger.warning(
                "Buyer preference loading failed; "
                "continuing without a memory hint: %s",
                error,
            )
            return [user_message]

        if not selected:
            self._injected_preferences.pop(
                intent.shopping_session_id,
                None,
            )
            return [user_message]

        rendered = render_preference_lines(
            selected,
        )

        if (
            self._injected_preferences.get(
                intent.shopping_session_id,
            )
            == rendered
        ):
            return [user_message]

        self._injected_preferences[
            intent.shopping_session_id
        ] = rendered

        memory_hint = UserMsg(
            name="memory_hint",
            content=render_preference_hint(
                selected,
            ),
        )

        return [
            memory_hint,
            user_message,
        ]

    async def _consume_reply(
        self,
        agent: Agent,
        messages: list[Msg],
        shopping_session_id: str,
    ) -> str:
        final_text = ""

        async for event in agent.reply_stream(
            messages,
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
