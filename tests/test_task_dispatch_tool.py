from dataclasses import dataclass, field

import pytest

from agentscope.message import (
    AssistantMsg,
    Msg,
    ToolResultState,
)
from agentscope.tool import FunctionTool

from app.application.tools.task_dispatch_tool import (
    build_task_dispatch_tool,
)


@dataclass
class RecordingAgent:
    response_text: str
    calls: list[list[Msg]] = field(default_factory=list)

    async def reply(self, messages: list[Msg]) -> Msg:
        self.calls.append(messages)
        return AssistantMsg(
            name="specialist",
            content=self.response_text,
        )


@dataclass
class RecordingFactory:
    response_text: str
    workers: list[RecordingAgent] = field(
        default_factory=list,
    )

    def build(self) -> RecordingAgent:
        worker = RecordingAgent(self.response_text)
        self.workers.append(worker)
        return worker


def build_recording_dispatcher():
    search_factory = RecordingFactory(
        '{"hits": ["P1001"]}',
    )
    trade_factory = RecordingFactory(
        '{"action": "query_order"}',
    )
    dispatcher = build_task_dispatch_tool(
        search_factory=search_factory,  # type: ignore[arg-type]
        trade_factory=trade_factory,  # type: ignore[arg-type]
    )
    return dispatcher, search_factory, trade_factory


def test_task_dispatch_tool_generates_expected_schema() -> None:
    dispatcher, _, _ = build_recording_dispatcher()

    function_tool = FunctionTool(
        dispatcher,
        is_read_only=False,
    )

    assert function_tool.name == "task_dispatch"
    assert function_tool.input_schema["required"] == [
        "subagent_type",
        "demands",
    ]
    assert function_tool.input_schema["properties"][
        "subagent_type"
    ]["enum"] == [
        "search_agent",
        "trade_agent",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subagent_type", "expected_text"),
    [
        ("search_agent", '{"hits": ["P1001"]}'),
        ("trade_agent", '{"action": "query_order"}'),
    ],
)
async def test_task_dispatch_routes_self_contained_task(
    subagent_type: str,
    expected_text: str,
) -> None:
    dispatcher, search_factory, trade_factory = (
        build_recording_dispatcher()
    )

    result = await dispatcher(
        subagent_type=subagent_type,  # type: ignore[arg-type]
        demands="  查找 300 元以内的旅行装备  ",
    )

    assert result.state == ToolResultState.SUCCESS
    assert result.content[0].text == expected_text

    selected_factory = (
        search_factory
        if subagent_type == "search_agent"
        else trade_factory
    )
    other_factory = (
        trade_factory
        if subagent_type == "search_agent"
        else search_factory
    )

    assert len(selected_factory.workers) == 1
    assert not other_factory.workers

    dispatched_message = (
        selected_factory.workers[0].calls[0][0]
    )
    assert dispatched_message.name == "commerce_concierge"
    assert dispatched_message.get_text_content() == (
        "查找 300 元以内的旅行装备"
    )


@pytest.mark.asyncio
async def test_each_dispatch_builds_fresh_agent() -> None:
    dispatcher, search_factory, _ = (
        build_recording_dispatcher()
    )

    await dispatcher(
        subagent_type="search_agent",
        demands="搜索旅行箱",
    )
    await dispatcher(
        subagent_type="search_agent",
        demands="搜索旅行背包",
    )

    assert len(search_factory.workers) == 2
    assert search_factory.workers[0] is not (
        search_factory.workers[1]
    )
    assert (
        search_factory.workers[0].calls[0][0]
        .get_text_content()
        == "搜索旅行箱"
    )
    assert (
        search_factory.workers[1].calls[0][0]
        .get_text_content()
        == "搜索旅行背包"
    )


@pytest.mark.asyncio
async def test_task_dispatch_rejects_empty_demands() -> None:
    dispatcher, search_factory, trade_factory = (
        build_recording_dispatcher()
    )

    result = await dispatcher(
        subagent_type="search_agent",
        demands="   ",
    )

    assert result.state == ToolResultState.ERROR
    assert result.content[0].text == (
        "[error] demands 不能为空"
    )
    assert not search_factory.workers
    assert not trade_factory.workers


@pytest.mark.asyncio
async def test_task_dispatch_rejects_unknown_agent_type() -> None:
    dispatcher, search_factory, trade_factory = (
        build_recording_dispatcher()
    )

    result = await dispatcher(
        subagent_type="unknown",  # type: ignore[arg-type]
        demands="执行任务",
    )

    assert result.state == ToolResultState.ERROR
    assert result.content[0].text == (
        "[error] 未知 subagent_type：unknown"
    )
    assert not search_factory.workers
    assert not trade_factory.workers
