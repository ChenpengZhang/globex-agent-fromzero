from dataclasses import FrozenInstanceError

import pytest

from app.domain.queue.ports.task_queue import (
    IntentTask,
    TaskQueue,
    TaskState,
    TaskStatus,
)


def task_values() -> dict:
    return {
        "task_id": " task-001 ",
        "shopping_session_id": " session-001 ",
        "buyer_id": " buyer-001 ",
        "locale": "",
        "currency": " cny ",
        "raw_query": " 推荐一个通勤杯 ",
        "enqueued_at": "2026-09-12T12:00:00+00:00",
        "priority": 0,
    }


def test_intent_task_normalizes_and_round_trips() -> None:
    task = IntentTask(**task_values())

    assert task.task_id == "task-001"
    assert task.shopping_session_id == "session-001"
    assert task.buyer_id == "buyer-001"
    assert task.locale == "zh-CN"
    assert task.currency == "CNY"
    assert task.raw_query == "推荐一个通勤杯"
    assert IntentTask.from_dict(task.to_dict()) == task


def test_intent_task_generates_missing_enqueue_time() -> None:
    raw = task_values()
    raw.pop("enqueued_at")

    task = IntentTask.from_dict(raw)

    assert task.enqueued_at
    assert "+00:00" in task.enqueued_at


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("task_id", " ", "task_id"),
        ("shopping_session_id", "", "shopping_session_id"),
        ("buyer_id", "", "buyer_id"),
        ("raw_query", "", "raw_query"),
        ("currency", "CN", "currency"),
        ("priority", -1, "priority"),
    ],
)
def test_intent_task_rejects_invalid_values(
    field: str,
    value: object,
    message: str,
) -> None:
    values = task_values()
    values[field] = value

    with pytest.raises(ValueError, match=message):
        IntentTask(**values)


def test_intent_task_is_immutable() -> None:
    task = IntentTask(**task_values())

    with pytest.raises(FrozenInstanceError):
        task.raw_query = "修改后的问题"  # type: ignore[misc]


def test_task_status_normalizes_and_round_trips() -> None:
    status = TaskStatus(
        task_id=" task-001 ",
        shopping_session_id=" session-001 ",
        buyer_id=" buyer-001 ",
        state="done",
        final_text="推荐结果",
    )

    assert status.task_id == "task-001"
    assert status.state is TaskState.DONE
    assert status.to_dict() == {
        "task_id": "task-001",
        "shopping_session_id": "session-001",
        "buyer_id": "buyer-001",
        "state": "done",
        "final_text": "推荐结果",
        "error": "",
        "queue_position": 0,
    }
    assert TaskStatus.from_dict(status.to_dict()) == status


@pytest.mark.parametrize(
    "state",
    list(TaskState),
)
def test_task_status_accepts_every_declared_state(
    state: TaskState,
) -> None:
    status = TaskStatus(
        task_id="task-001",
        shopping_session_id="session-001",
        buyer_id="buyer-001",
        state=state,
    )

    assert status.state is state


def test_task_status_rejects_unknown_state() -> None:
    with pytest.raises(ValueError, match="Unsupported task state"):
        TaskStatus(
            task_id="task-001",
            shopping_session_id="session-001",
            buyer_id="buyer-001",
            state="runing",
        )


def test_task_status_rejects_negative_queue_position() -> None:
    with pytest.raises(ValueError, match="queue_position"):
        TaskStatus(
            task_id="task-001",
            shopping_session_id="session-001",
            buyer_id="buyer-001",
            state=TaskState.QUEUED,
            queue_position=-1,
        )


def test_task_queue_cannot_omit_required_operations() -> None:
    class IncompleteTaskQueue(TaskQueue):
        pass

    with pytest.raises(TypeError):
        IncompleteTaskQueue()
