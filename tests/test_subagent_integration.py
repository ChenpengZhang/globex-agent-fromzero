import json

import pytest

from agentscope.message import (
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from agentscope.model import ChatResponse

import app.composition as composition
from app.application.agents.orchestrator import (
    SubmitIntentInput,
)
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
async def test_main_agent_dispatches_isolated_search_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specialist_summary = (
        '{"hits": ["P1001", "P1003"], '
        '"notes": "两件商品符合预算和配送要求"}'
    )
    model = ScriptedChatModel(
        responses=[
            tool_call_response(
                "call-dispatch-1",
                "task_dispatch",
                {
                    "subagent_type": "search_agent",
                    "demands": (
                        "搜索 300 CNY 以内、可配送到 CN "
                        "的轻便旅行装备"
                    ),
                },
            ),
            tool_call_response(
                "call-search-1",
                "product_search_tool",
                {
                    "normalized_query": "旅行装备 轻便",
                    "category": "旅行装备",
                    "ship_to": "CN",
                    "top_k": 5,
                    "price_max_major": 300,
                    "target_currency": "CNY",
                },
            ),
            text_response(specialist_summary),
            text_response(
                "推荐 P1001 和 P1003，均符合预算并可配送到中国。"
            ),
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

    reply = await container.orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-subagent-001",
            buyer_id="buyer-001",
            locale="zh-CN",
            currency="CNY",
            raw_query=(
                "请深入比较 300 元以内、"
                "能寄到中国的轻便旅行装备"
            ),
        )
    )

    assert reply.final_text == (
        "推荐 P1001 和 P1003，均符合预算并可配送到中国。"
    )
    assert len(model.calls) == 4

    main_tool_names = {
        tool["function"]["name"]
        for tool in model.calls[0]["tools"]
    }
    assert main_tool_names == {
        "product_search_tool",
        "place_order_tool",
        "query_order_tool",
        "cancel_order_tool",
        "task_dispatch",
    }

    specialist_tool_names = {
        tool["function"]["name"]
        for tool in model.calls[1]["tools"]
    }
    assert specialist_tool_names == {
        "product_search_tool",
    }

    specialist_results = collect_tool_result_texts(
        model.calls[2]["messages"]
    )
    assert any(
        "P1001" in text
        and "P1003" in text
        and "filtered_out" in text
        for text in specialist_results
    )

    main_results = collect_tool_result_texts(
        model.calls[3]["messages"]
    )
    assert specialist_summary in main_results
    assert all(
        "filtered_out" not in text
        for text in main_results
    )
    assert ShoppingContext.current() is None


@pytest.mark.asyncio
async def test_trade_agent_dispatch_preserves_buyer_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specialist_summary = (
        '{"action": "place_order", '
        '"order_id": "GBX-000001", '
        '"status": "CONFIRMED"}'
    )
    model = ScriptedChatModel(
        responses=[
            tool_call_response(
                "call-trade-dispatch-1",
                "task_dispatch",
                {
                    "subagent_type": "trade_agent",
                    "demands": (
                        "用户已明确确认购买 2 件 P1001-S1。"
                        "收件人 Alice，国家 CN，省市均为上海，"
                        "地址南京西路 1 号，邮编 200000，"
                        "电话 13800000000。创建订单。"
                    ),
                },
            ),
            tool_call_response(
                "call-place-from-trade-1",
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
            text_response(specialist_summary),
            text_response("订单 GBX-000001 已创建。"),
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

    product = await container.product_repository.find_by_id(
        "P1001"
    )
    assert product is not None
    sku = product.find_sku("P1001-S1")
    assert sku is not None
    initial_stock = sku.stock

    reply = await container.orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id="session-trade-agent-001",
            buyer_id="buyer-through-context",
            locale="zh-CN",
            currency="CNY",
            raw_query="确认使用以上信息下单。",
        )
    )

    assert reply.final_text == "订单 GBX-000001 已创建。"
    assert len(model.calls) == 4

    trade_tool_names = {
        tool["function"]["name"]
        for tool in model.calls[1]["tools"]
    }
    assert trade_tool_names == {
        "place_order_tool",
        "query_order_tool",
        "cancel_order_tool",
    }

    trade_results = collect_tool_result_texts(
        model.calls[2]["messages"]
    )
    assert any(
        '"buyer_id": "buyer-through-context"' in text
        and '"status": "CONFIRMED"' in text
        for text in trade_results
    )

    main_results = collect_tool_result_texts(
        model.calls[3]["messages"]
    )
    assert specialist_summary in main_results

    stored = await container.order_repository.find_by_id(
        "GBX-000001"
    )
    assert stored is not None
    assert stored.buyer_id == "buyer-through-context"
    assert stored.status is OrderStatus.CONFIRMED
    assert sku.stock == initial_stock - 2
    assert ShoppingContext.current() is None
