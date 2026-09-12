import json

import pytest

from agentscope.message import (
    TextBlock,
    ToolCallBlock,
)
from agentscope.model import ChatResponse

import app.composition as composition
from app.application.agents.orchestrator import (
    SubmitIntentInput,
)
from app.infrastructure.context import ShoppingContext
from app.infrastructure.persistence.sql.database import (
    bootstrap_schema,
)
from tests.fakes import (
    DeterministicEmbeddingClient,
    EmptyKnowledgeBase,
    RecordingProductVectorIndex,
    ScriptedChatModel,
    build_composition_settings,
)


def tool_call_response(
    call_id: str,
    name: str,
    arguments: dict,
) -> ChatResponse:
    return ChatResponse(
        content=[
            ToolCallBlock(
                id=call_id,
                name=name,
                input=json.dumps(
                    arguments,
                    ensure_ascii=False,
                ),
            )
        ],
        is_last=True,
    )


def text_response(text: str) -> ChatResponse:
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
    session_id: str,
    query: str,
) -> SubmitIntentInput:
    return SubmitIntentInput(
        shopping_session_id=session_id,
        buyer_id="buyer-memory-owner",
        locale="zh-CN",
        currency="CNY",
        raw_query=query,
    )


def memory_hints(messages) -> list[str]:
    return [
        message.get_text_content() or ""
        for message in messages
        if message.name == "memory_hint"
    ]


@pytest.mark.asyncio
async def test_agent_remembers_reads_and_forgets_across_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statement = "不要塑料材质"
    model = ScriptedChatModel(
        responses=[
            tool_call_response(
                "call-remember-1",
                "remember_preference_tool",
                {
                    "kind": "dislike",
                    "statement": statement,
                },
            ),
            text_response("好的，我会长期记住这个偏好。"),
            text_response("我会避开塑料材质。"),
            tool_call_response(
                "call-forget-1",
                "forget_preference_tool",
                {"statement": statement},
            ),
            text_response("已撤回这个长期偏好。"),
            text_response("当前没有需要应用的长期偏好。"),
        ]
    )
    monkeypatch.setattr(
        composition,
        "load_settings",
        build_composition_settings,
    )
    monkeypatch.setattr(
        composition,
        "create_chat_model",
        lambda settings: model,
    )
    monkeypatch.setattr(
        composition,
        "build_category_knowledge_base",
        lambda settings: EmptyKnowledgeBase(),
    )
    monkeypatch.setattr(
        composition,
        "OpenAIEmbeddingClient",
        lambda settings: DeterministicEmbeddingClient(),
    )
    monkeypatch.setattr(
        composition,
        "QdrantProductIndex",
        lambda settings: RecordingProductVectorIndex(),
    )
    container = composition.build_container()
    await bootstrap_schema(container.database_engine)

    try:
        remembered = await container.orchestrator.handle_intent(
            intent(
                "session-remember",
                "以后给我推荐商品时，不要塑料材质。",
            )
        )

        stored = await container.preference_store.list_by_buyer(
            "buyer-memory-owner"
        )

        assert remembered.final_text == (
            "好的，我会长期记住这个偏好。"
        )
        assert [item.statement for item in stored] == [statement]

        read_reply = await container.orchestrator.handle_intent(
            intent(
                "session-read",
                "推荐一个适合通勤的水杯。",
            )
        )

        assert read_reply.final_text == "我会避开塑料材质。"
        read_hints = memory_hints(model.calls[2]["messages"])
        assert len(read_hints) == 1
        assert f"[dislike] {statement}" in read_hints[0]

        forgotten = await container.orchestrator.handle_intent(
            intent(
                "session-forget",
                "我撤回不要塑料材质这个长期偏好。",
            )
        )

        assert forgotten.final_text == "已撤回这个长期偏好。"
        assert await container.preference_store.list_by_buyer(
            "buyer-memory-owner"
        ) == []

        after_forget = await container.orchestrator.handle_intent(
            intent(
                "session-after-forget",
                "再推荐一个水杯。",
            )
        )

        assert after_forget.final_text == (
            "当前没有需要应用的长期偏好。"
        )
        assert memory_hints(model.calls[5]["messages"]) == []
        assert ShoppingContext.current() is None
    finally:
        await container.database_engine.dispose()
