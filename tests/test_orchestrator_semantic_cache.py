import pytest

from agentscope.message import TextBlock
from agentscope.model import ChatResponse

from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import (
    MainAgentOrchestrator,
    SubmitIntentInput,
)
from app.application.agents.session_registry import SessionRegistry
from app.application.events import TradeEventType
from app.domain.buyer.preference import BuyerPreference
from app.infrastructure.cache.semantic_cache import (
    SemanticHit,
    is_cacheable_query,
)
from app.infrastructure.eventbus import InMemoryTradeEventBus
from tests.fakes import (
    InMemoryConversationStore,
    InMemoryPreferenceStore,
    InMemorySessionStore,
    ScriptedChatModel,
)


class RecordingSemanticCache:
    """Semantic cache test double with observable lookup calls."""

    def __init__(
        self,
        hit: SemanticHit | None = None,
        lookup_error: Exception | None = None,
        remember_error: Exception | None = None,
    ) -> None:
        self.preset_hit = hit
        self.lookup_error = lookup_error
        self.remember_error = remember_error
        self.lookup_calls: list[dict] = []
        self.remember_calls: list[dict] = []
        self.stored_hits: dict[
            tuple[str, str],
            SemanticHit,
        ] = {}

    async def lookup(
        self,
        buyer_id: str,
        query: str,
        has_history: bool,
        scope: str = "",
    ) -> SemanticHit | None:
        self.lookup_calls.append(
            {
                "buyer_id": buyer_id,
                "query": query,
                "has_history": has_history,
                "scope": scope,
            }
        )

        if self.lookup_error is not None:
            raise self.lookup_error

        if has_history:
            return None

        return self.stored_hits.get(
            (buyer_id, scope),
            self.preset_hit,
        )

    async def remember(
        self,
        buyer_id: str,
        query: str,
        reply: str,
        has_history: bool,
        scope: str = "",
    ) -> None:
        self.remember_calls.append(
            {
                "buyer_id": buyer_id,
                "query": query,
                "reply": reply,
                "has_history": has_history,
                "scope": scope,
            }
        )

        if self.remember_error is not None:
            raise self.remember_error

        if (
            has_history
            or not is_cacheable_query(query)
            or not reply
            or reply.startswith("[error]")
        ):
            return

        self.stored_hits[(buyer_id, scope)] = SemanticHit(
            reply=reply,
            similarity=1.0,
            matched_query=query,
        )


class FailingHistoryStore(InMemoryConversationStore):
    async def list_turns(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list:
        raise RuntimeError("conversation database unavailable")


class FailingPreferenceStore(InMemoryPreferenceStore):
    async def list_by_buyer(
        self,
        buyer_id: str,
    ) -> list[BuyerPreference]:
        raise RuntimeError("preference database unavailable")


def response(text: str) -> ChatResponse:
    return ChatResponse(
        content=[
            TextBlock(
                type="text",
                text=text,
            )
        ],
        is_last=True,
    )


def intent(
    session_id: str = "session-001",
    query: str = "推荐一个适合通勤的杯子",
) -> SubmitIntentInput:
    return SubmitIntentInput(
        shopping_session_id=session_id,
        buyer_id="buyer-001",
        locale="zh-CN",
        currency="CNY",
        raw_query=query,
    )


def build_orchestrator(
    *,
    cache: RecordingSemanticCache,
    responses: list[ChatResponse],
    conversation_store: InMemoryConversationStore | None = None,
    preference_store: InMemoryPreferenceStore | None = None,
) -> tuple[
    MainAgentOrchestrator,
    ScriptedChatModel,
    InMemoryTradeEventBus,
]:
    model = ScriptedChatModel(responses=responses)
    sessions = SessionRegistry(
        MainAgentFactory(model=model, tools=[]),
        InMemorySessionStore(),
    )
    event_bus = InMemoryTradeEventBus()
    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
        event_bus=event_bus,
        conversation_store=(
            conversation_store
            if conversation_store is not None
            else InMemoryConversationStore()
        ),
        semantic_cache=cache,
        preference_store=preference_store,
    )
    return orchestrator, model, event_bus


@pytest.mark.asyncio
async def test_cache_hit_skips_agent_and_persists_trace() -> None:
    cache = RecordingSemanticCache(
        SemanticHit(
            reply="缓存中的推荐",
            similarity=0.98,
            matched_query="推荐一个通勤杯",
        )
    )
    conversations = InMemoryConversationStore()
    orchestrator, model, event_bus = build_orchestrator(
        cache=cache,
        responses=[],
        conversation_store=conversations,
    )
    events = event_bus.subscribe("session-001")

    result = await orchestrator.handle_intent(intent())

    assert result.final_text == "缓存中的推荐"
    assert model.calls == []
    assert cache.remember_calls == []
    assert cache.lookup_calls[0]["has_history"] is False
    assert [events.get_nowait().type for _ in range(2)] == [
        TradeEventType.CACHE_HIT,
        TradeEventType.FINAL_RESULT,
    ]
    assert events.empty()
    assert [turn.content for turn in conversations.turns] == [
        "推荐一个适合通勤的杯子",
        "缓存中的推荐",
    ]
    assert [event.type for event in conversations.events] == [
        "cache.hit",
        "final.result",
    ]


@pytest.mark.asyncio
async def test_persisted_turn_disables_cache_on_second_request() -> None:
    cache = RecordingSemanticCache(
        SemanticHit(
            reply="第一轮缓存回答",
            similarity=0.99,
            matched_query="推荐杯子",
        )
    )
    conversations = InMemoryConversationStore()
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[response("第二轮模型回答")],
        conversation_store=conversations,
    )

    first = await orchestrator.handle_intent(intent())
    second = await orchestrator.handle_intent(
        intent(query="还有其他选择吗")
    )

    assert first.final_text == "第一轮缓存回答"
    assert second.final_text == "第二轮模型回答"
    assert len(model.calls) == 1
    assert [
        call["has_history"]
        for call in cache.lookup_calls
    ] == [False, True]
    assert cache.remember_calls[0]["has_history"] is True
    assert cache.stored_hits == {}


@pytest.mark.asyncio
async def test_cache_miss_calls_agent() -> None:
    cache = RecordingSemanticCache()
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[response("模型生成的回答")],
    )

    result = await orchestrator.handle_intent(intent())

    assert result.final_text == "模型生成的回答"
    assert len(model.calls) == 1
    assert len(cache.lookup_calls) == 1
    assert cache.remember_calls == [
        {
            "buyer_id": "buyer-001",
            "query": "推荐一个适合通勤的杯子",
            "reply": "模型生成的回答",
            "has_history": False,
            "scope": "",
        }
    ]


@pytest.mark.asyncio
async def test_first_session_populates_cache_for_new_session() -> None:
    cache = RecordingSemanticCache()
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[response("首轮模型回答")],
    )

    first = await orchestrator.handle_intent(
        intent(session_id="session-A")
    )
    second = await orchestrator.handle_intent(
        intent(session_id="session-B")
    )

    assert first.final_text == "首轮模型回答"
    assert second.final_text == "首轮模型回答"
    assert len(model.calls) == 1
    assert len(cache.remember_calls) == 1
    assert [
        call["has_history"]
        for call in cache.lookup_calls
    ] == [False, False]


@pytest.mark.asyncio
async def test_unsafe_query_is_not_stored() -> None:
    cache = RecordingSemanticCache()
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[response("请确认订单")],
    )

    result = await orchestrator.handle_intent(
        intent(query="帮我下单购买这个杯子")
    )

    assert result.final_text == "请确认订单"
    assert len(model.calls) == 1
    assert len(cache.remember_calls) == 1
    assert cache.stored_hits == {}


@pytest.mark.asyncio
async def test_preference_change_uses_a_new_cache_scope() -> None:
    cache = RecordingSemanticCache()
    preferences = InMemoryPreferenceStore()
    await preferences.append(
        BuyerPreference(
            buyer_id="buyer-001",
            kind="like",
            statement="喜欢玻璃材质",
        )
    )
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[
            response("玻璃杯推荐"),
            response("保温杯推荐"),
        ],
        preference_store=preferences,
    )

    first = await orchestrator.handle_intent(
        intent(session_id="session-A")
    )
    await preferences.append(
        BuyerPreference(
            buyer_id="buyer-001",
            kind="like",
            statement="喜欢保温性能",
        )
    )
    second = await orchestrator.handle_intent(
        intent(session_id="session-B")
    )

    assert first.final_text == "玻璃杯推荐"
    assert second.final_text == "保温杯推荐"
    assert len(model.calls) == 2
    assert (
        cache.lookup_calls[0]["scope"]
        != cache.lookup_calls[1]["scope"]
    )


@pytest.mark.asyncio
async def test_history_lookup_failure_disables_cache() -> None:
    cache = RecordingSemanticCache(
        SemanticHit(
            reply="不应使用的缓存回答",
            similarity=1.0,
            matched_query="推荐杯子",
        )
    )
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[response("安全回退到模型")],
        conversation_store=FailingHistoryStore(),
    )

    result = await orchestrator.handle_intent(intent())

    assert result.final_text == "安全回退到模型"
    assert len(model.calls) == 1
    assert cache.lookup_calls[0]["has_history"] is True


@pytest.mark.asyncio
async def test_preference_lookup_failure_skips_cache() -> None:
    cache = RecordingSemanticCache(
        SemanticHit(
            reply="不应使用的缓存回答",
            similarity=1.0,
            matched_query="推荐杯子",
        )
    )
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[response("安全回退到模型")],
        preference_store=FailingPreferenceStore(),
    )

    result = await orchestrator.handle_intent(intent())

    assert result.final_text == "安全回退到模型"
    assert len(model.calls) == 1
    assert cache.lookup_calls == []


@pytest.mark.asyncio
async def test_unexpected_cache_error_falls_back_to_agent() -> None:
    cache = RecordingSemanticCache(
        lookup_error=RuntimeError("cache unavailable"),
    )
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[response("模型仍然可用")],
    )

    result = await orchestrator.handle_intent(intent())

    assert result.final_text == "模型仍然可用"
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_cache_write_error_does_not_replace_agent_reply() -> None:
    cache = RecordingSemanticCache(
        remember_error=RuntimeError("cache unavailable"),
    )
    orchestrator, model, _ = build_orchestrator(
        cache=cache,
        responses=[response("模型正常回答")],
    )

    result = await orchestrator.handle_intent(intent())

    assert result.final_text == "模型正常回答"
    assert len(model.calls) == 1
    assert len(cache.remember_calls) == 1
