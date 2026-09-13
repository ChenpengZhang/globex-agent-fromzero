from types import SimpleNamespace

import pytest

from app.application.agents.orchestrator import SubmitIntentOutput
from app.application.events import TradeEventType
from app.domain.queue.ports.task_queue import (
    IntentTask,
    TaskState,
    TaskStatus,
)
from app.infrastructure.eventbus import InMemoryTradeEventBus
from app.worker import process_task


class RecordingTaskQueue:
    def __init__(self) -> None:
        self.statuses: list[TaskStatus] = []

    async def set_status(self, status: TaskStatus) -> None:
        self.statuses.append(status)


class RecordingOrchestrator:
    def __init__(
        self,
        final_text: str = "推荐结果",
        error: Exception | None = None,
    ) -> None:
        self.final_text = final_text
        self.error = error
        self.intents = []

    async def handle_intent(self, intent):
        self.intents.append(intent)

        if self.error is not None:
            raise self.error

        return SubmitIntentOutput(
            shopping_session_id=intent.shopping_session_id,
            final_text=self.final_text,
        )


def intent_task() -> IntentTask:
    return IntentTask(
        task_id="task-001",
        shopping_session_id="session-001",
        buyer_id="buyer-001",
        locale="zh-CN",
        currency="CNY",
        raw_query="推荐一个通勤杯",
    )


@pytest.mark.asyncio
async def test_process_task_runs_orchestrator_and_marks_done() -> None:
    queue = RecordingTaskQueue()
    orchestrator = RecordingOrchestrator()
    event_bus = InMemoryTradeEventBus()
    events = event_bus.subscribe("session-001")
    container = SimpleNamespace(
        task_queue=queue,
        orchestrator=orchestrator,
        event_bus=event_bus,
    )

    await process_task(container, intent_task())

    assert [status.state for status in queue.statuses] == [
        TaskState.RUNNING,
        TaskState.DONE,
    ]
    assert queue.statuses[-1].final_text == "推荐结果"
    assert len(orchestrator.intents) == 1
    submitted = orchestrator.intents[0]
    assert submitted.shopping_session_id == "session-001"
    assert submitted.buyer_id == "buyer-001"
    assert submitted.raw_query == "推荐一个通勤杯"
    started = events.get_nowait()
    assert started.type is TradeEventType.TASK_STARTED
    assert started.payload == {"task_id": "task-001"}


@pytest.mark.asyncio
async def test_process_task_leaves_retry_policy_to_queue() -> None:
    queue = RecordingTaskQueue()
    orchestrator = RecordingOrchestrator(
        error=RuntimeError("model unavailable"),
    )
    container = SimpleNamespace(
        task_queue=queue,
        orchestrator=orchestrator,
        event_bus=InMemoryTradeEventBus(),
    )

    with pytest.raises(RuntimeError, match="model unavailable"):
        await process_task(container, intent_task())

    assert [status.state for status in queue.statuses] == [
        TaskState.RUNNING,
    ]


@pytest.mark.asyncio
async def test_process_task_requires_queue() -> None:
    container = SimpleNamespace(
        task_queue=None,
        orchestrator=RecordingOrchestrator(),
        event_bus=InMemoryTradeEventBus(),
    )

    with pytest.raises(RuntimeError, match="unavailable"):
        await process_task(container, intent_task())
