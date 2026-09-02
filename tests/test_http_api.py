import re

import pytest
from fastapi.testclient import TestClient

from agentscope.message import TextBlock
from agentscope.model import ChatResponse

from app.application.agents.main_agent import create_main_agent
from app.application.agents.orchestrator import MainAgentOrchestrator
from app.application.usecases.catalog_search import CatalogSearchUseCase
from app.composition import Container
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import build_seed_products
from app.presentation.server import build_app
from tests.fakes import ScriptedChatModel


def build_test_container(
    final_text: str = "测试回复",
) -> tuple[Container, ScriptedChatModel]:
    model = ScriptedChatModel(
        responses=[
            ChatResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=final_text,
                    ),
                ],
                is_last=True,
            ),
        ],
    )

    repository = InMemoryProductRepository(
        build_seed_products(),
    )
    catalog_search = CatalogSearchUseCase(repository)
    main_agent = create_main_agent(
        model=model,
        tools=[],
    )
    orchestrator = MainAgentOrchestrator(
        main_agent=main_agent,
    )

    return (
        Container(
            main_agent=main_agent,
            orchestrator=orchestrator,
            product_repository=repository,
            catalog_search=catalog_search,
        ),
        model,
    )


def test_health_endpoint() -> None:
    container, _ = build_test_container()

    with TestClient(build_app(container)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_submit_intent_generates_session_and_uses_defaults() -> None:
    container, model = build_test_container(
        final_text="默认上下文测试回复",
    )

    with TestClient(build_app(container)) as client:
        response = client.post(
            "/commerce/intents",
            json={
                "buyer_id": "buyer-001",
                "raw_query": "你好",
            },
        )

    assert response.status_code == 200

    payload = response.json()
    assert re.fullmatch(
        r"session-[0-9a-f]{8}",
        payload["shopping_session_id"],
    )
    assert payload["final_text"] == "默认上下文测试回复"

    sent_messages = model.calls[0]["messages"]
    buyer_message = next(
        message
        for message in sent_messages
        if message.role == "user"
        and message.name == "buyer-001"
    )
    content = buyer_message.get_text_content() or ""

    assert "locale: zh-CN" in content
    assert "currency: CNY" in content
    assert "你好" in content


def test_submit_intent_preserves_session_and_normalizes_currency() -> None:
    container, model = build_test_container(
        final_text="指定会话测试回复",
    )

    with TestClient(build_app(container)) as client:
        response = client.post(
            "/commerce/intents",
            json={
                "shopping_session_id": "session-custom",
                "buyer_id": "buyer-002",
                "locale": "en-US",
                "currency": "usd",
                "raw_query": "Find travel gear",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "shopping_session_id": "session-custom",
        "final_text": "指定会话测试回复",
    }

    sent_messages = model.calls[0]["messages"]
    buyer_message = next(
        message
        for message in sent_messages
        if message.role == "user"
        and message.name == "buyer-002"
    )
    content = buyer_message.get_text_content() or ""

    assert "locale: en-US" in content
    assert "currency: USD" in content
    assert "Find travel gear" in content


@pytest.mark.parametrize(
    "payload",
    [
        {
            "raw_query": "你好",
        },
        {
            "buyer_id": "buyer-001",
        },
        {
            "buyer_id": "buyer-001",
            "raw_query": "   ",
        },
        {
            "buyer_id": "buyer-001",
            "currency": "CN",
            "raw_query": "你好",
        },
    ],
)
def test_submit_intent_rejects_invalid_http_payload(
    payload: dict,
) -> None:
    container, _ = build_test_container()

    with TestClient(build_app(container)) as client:
        response = client.post(
            "/commerce/intents",
            json=payload,
        )

    assert response.status_code == 422
