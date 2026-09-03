import json

import pytest

from agentscope.message import (
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from agentscope.model import ChatResponse

import app.composition as composition
from app.application.agents.orchestrator import SubmitIntentInput
from app.domain.order.order import OrderStatus
from app.infrastructure.context import ShoppingContext
from tests.fakes import ScriptedChatModel


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


def collect_tool_result_texts(messages) -> list[str]:
    texts: list[str] = []

    for message in messages:
        for block in message.get_content_blocks():
            if not isinstance(block, ToolResultBlock):
                continue

            if isinstance(block.output, str):
                texts.append(block.output)
                continue

            texts.extend(
                item.text
                for item in block.output
                if isinstance(item, TextBlock)
            )

    return texts


@pytest.mark.asyncio
async def test_agent_places_queries_and_cancels_order_in_one_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ScriptedChatModel(
        responses=[
            tool_call_response(
                "call-place-1",
                "place_order_tool",
                {
                    "items": [
                        {
                            "product_id": "P1001",
                            "sku_id": "P1001-S1",
                            "quantity": 2,
                        }
                    ],
                    "shipping_address": {
                        "recipient_name": "Alice",
                        "country": "CN",
                        "state": "上海",
                        "city": "上海",
                        "address_line": "南京西路 1 号",
                        "postal_code": "200000",
                        "phone": "13800000000",
                    },
                },
            ),
            text_response("订单 GBX-000001 已创建。"),
            tool_call_response(
                "call-query-1",
                "query_order_tool",
                {"order_id": "GBX-000001"},
            ),
            text_response("订单 GBX-000001 当前已确认。"),
            tool_call_response(
                "call-cancel-1",
                "cancel_order_tool",
                {
                    "order_id": "GBX-000001",
                    "reason": "改变购买计划",
                },
            ),
            text_response("订单 GBX-000001 已取消。"),
        ]
    )
    monkeypatch.setattr(
        composition,
        "load_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        composition,
        "create_chat_model",
        lambda settings: model,
    )
    container = composition.build_container()

    product = await container.product_repository.find_by_id("P1001")
    assert product is not None
    sku = product.find_sku("P1001-S1")
    assert sku is not None
    initial_stock = sku.stock

    placed_reply = await container.orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-001",
            buyer_id="buyer-001",
            locale="zh-CN",
            currency="CNY",
            raw_query=(
                "我确认购买 2 件 P1001-S1，"
                "并使用刚才提供的收货地址。"
            ),
        )
    )
    queried_reply = await container.orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-001",
            buyer_id="buyer-001",
            locale="zh-CN",
            currency="CNY",
            raw_query="查询订单 GBX-000001。",
        )
    )
    cancelled_reply = await container.orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-001",
            buyer_id="buyer-001",
            locale="zh-CN",
            currency="CNY",
            raw_query=(
                "取消订单 GBX-000001，"
                "原因是改变购买计划。"
            ),
        )
    )

    assert placed_reply.final_text == "订单 GBX-000001 已创建。"
    assert queried_reply.final_text == "订单 GBX-000001 当前已确认。"
    assert cancelled_reply.final_text == "订单 GBX-000001 已取消。"
    assert len(model.calls) == 6

    available_tool_names = {
        tool["function"]["name"]
        for tool in model.calls[0]["tools"]
    }
    assert available_tool_names == {
        "product_search_tool",
        "place_order_tool",
        "query_order_tool",
        "cancel_order_tool",
    }

    place_results = collect_tool_result_texts(
        model.calls[1]["messages"]
    )
    query_results = collect_tool_result_texts(
        model.calls[3]["messages"]
    )
    cancel_results = collect_tool_result_texts(
        model.calls[5]["messages"]
    )
    assert any(
        '"buyer_id": "buyer-001"' in text
        and '"status": "CONFIRMED"' in text
        for text in place_results
    )
    assert any(
        '"order_id": "GBX-000001"' in text
        for text in query_results
    )
    assert any(
        '"status": "CANCELLED"' in text
        for text in cancel_results
    )

    stored = await container.order_repository.find_by_id("GBX-000001")
    assert stored is not None
    assert stored.buyer_id == "buyer-001"
    assert stored.status is OrderStatus.CANCELLED
    assert sku.stock == initial_stock
    assert ShoppingContext.current() is None
