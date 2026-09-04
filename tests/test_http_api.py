import re

import pytest
from fastapi.testclient import TestClient

from agentscope.message import TextBlock
from agentscope.model import ChatResponse

from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import MainAgentOrchestrator
from app.application.agents.search_agent import SearchAgentFactory
from app.application.agents.session_registry import SessionRegistry
from app.application.agents.trade_agent import TradeAgentFactory
from app.application.usecases.cancel_order import CancelOrderUseCase
from app.application.usecases.catalog_search import CatalogSearchUseCase
from app.application.usecases.place_order import PlaceOrderUseCase
from app.application.usecases.query_order import QueryOrderUseCase
from app.composition import Container
from app.infrastructure.persistence.in_memory_order_repository import (
    InMemoryOrderRepository,
)
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
    order_repository = InMemoryOrderRepository()
    place_order = PlaceOrderUseCase(repository, order_repository)
    query_order = QueryOrderUseCase(order_repository)
    cancel_order = CancelOrderUseCase(repository, order_repository)
    main_agent_factory = MainAgentFactory(
        model=model,
        tools=[],
    )
    search_agent_factory = SearchAgentFactory(
        model=model,
        catalog_search=catalog_search,
    )
    trade_agent_factory = TradeAgentFactory(
        model=model,
        place_order=place_order,
        query_order=query_order,
        cancel_order=cancel_order,
    )
    sessions = SessionRegistry(main_agent_factory)
    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
    )

    return (
        Container(
            main_agent_factory=main_agent_factory,
            search_agent_factory=search_agent_factory,
            trade_agent_factory=trade_agent_factory,
            sessions=sessions,
            orchestrator=orchestrator,
            product_repository=repository,
            order_repository=order_repository,
            catalog_search=catalog_search,
            place_order=place_order,
            query_order=query_order,
            cancel_order=cancel_order,
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


def test_submit_intent_rejects_session_reuse_by_other_buyer() -> None:
    container, _ = build_test_container()

    with TestClient(build_app(container)) as client:
        first_response = client.post(
            "/commerce/intents",
            json={
                "shopping_session_id": "session-shared",
                "buyer_id": "buyer-001",
                "raw_query": "你好",
            },
        )

        second_response = client.post(
            "/commerce/intents",
            json={
                "shopping_session_id": "session-shared",
                "buyer_id": "buyer-002",
                "raw_query": "你好",
            },
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert "已绑定到其他 buyer" in second_response.json()["detail"]


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
