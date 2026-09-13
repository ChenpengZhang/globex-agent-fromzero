import json

import pytest
from redis.exceptions import ResponseError

from app.domain.queue.ports.task_queue import (
    IntentTask,
    TaskState,
    TaskStatus,
)
from app.infrastructure.queue.redis_stream_queue import (
    RedisStreamTaskQueue,
)


class FakeRedisStreamClient:
    """Small Redis double for queue storage and status tests."""

    def __init__(self) -> None:
        self.group_calls: list[dict] = []
        self.entries: list[tuple[str, dict]] = []
        self.acked: list[tuple[str, str, str]] = []
        self.values: dict[str, str] = {}
        self.set_calls: list[dict] = []
        self.group_error: ResponseError | None = None
        self.group_info: dict[str, list[dict]] = {}
        self.info_errors: set[str] = set()
        self.read_calls: list[dict] = []
        self.read_results: list[list] = []
        self.claim_calls: list[dict] = []
        self.claim_results: dict[str, list] = {}
        self.claim_errors: set[str] = set()
        self.delivery_counts: dict[str, int] = {}

    def pipeline(
        self,
        transaction: bool,
    ) -> "FakeRedisPipeline":
        assert transaction is True
        return FakeRedisPipeline(self)

    async def xgroup_create(self, **kwargs) -> None:
        self.group_calls.append(kwargs)

        if self.group_error is not None:
            raise self.group_error

    async def xadd(
        self,
        stream: str,
        fields: dict,
    ) -> str:
        self.entries.append((stream, fields))
        return f"{len(self.entries)}-0"

    async def set(
        self,
        key: str,
        value: str,
        ex: int,
    ) -> bool:
        self.values[key] = value
        self.set_calls.append(
            {
                "key": key,
                "value": value,
                "ex": ex,
            }
        )
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def xinfo_groups(
        self,
        stream: str,
    ) -> list[dict]:
        if stream in self.info_errors:
            raise RuntimeError("stream unavailable")

        return self.group_info.get(stream, [])

    async def xreadgroup(self, **kwargs) -> list:
        self.read_calls.append(kwargs)

        if self.read_results:
            return self.read_results.pop(0)

        return []

    async def xautoclaim(self, **kwargs) -> list:
        self.claim_calls.append(kwargs)
        stream = kwargs["name"]

        if stream in self.claim_errors:
            raise RuntimeError("claim unavailable")

        return self.claim_results.get(
            stream,
            ["0-0", [], []],
        )

    async def xack(
        self,
        stream: str,
        group: str,
        message_id: str,
    ) -> int:
        self.acked.append((stream, group, message_id))
        return 1

    async def xpending_range(self, **kwargs) -> list[dict]:
        message_id = kwargs["min"]
        return [
            {
                "times_delivered": self.delivery_counts.get(
                    message_id,
                    1,
                )
            }
        ]


class FakeRedisPipeline:
    def __init__(
        self,
        client: FakeRedisStreamClient,
    ) -> None:
        self._client = client
        self._commands: list[tuple[str, tuple, dict]] = []

    async def __aenter__(self) -> "FakeRedisPipeline":
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        return None

    def xadd(
        self,
        *args,
        **kwargs,
    ) -> "FakeRedisPipeline":
        self._commands.append(("xadd", args, kwargs))
        return self

    def set(
        self,
        *args,
        **kwargs,
    ) -> "FakeRedisPipeline":
        self._commands.append(("set", args, kwargs))
        return self

    async def execute(self) -> list:
        results = []

        for method_name, args, kwargs in self._commands:
            method = getattr(self._client, method_name)
            results.append(await method(*args, **kwargs))

        return results


def task(
    *,
    task_id: str = "task-001",
    priority: int = 0,
) -> IntentTask:
    return IntentTask(
        task_id=task_id,
        shopping_session_id="session-001",
        buyer_id="buyer-001",
        locale="zh-CN",
        currency="CNY",
        raw_query="推荐一个通勤杯",
        priority=priority,
    )


@pytest.mark.asyncio
async def test_ensure_ready_creates_both_stream_groups() -> None:
    client = FakeRedisStreamClient()
    queue = RedisStreamTaskQueue(client)

    await queue.ensure_ready()

    assert [
        call["name"]
        for call in client.group_calls
    ] == [
        "globex:intents",
        "globex:intents:large",
    ]
    assert all(
        call["groupname"] == "globex-workers"
        and call["id"] == "0"
        and call["mkstream"] is True
        for call in client.group_calls
    )


@pytest.mark.asyncio
async def test_ensure_ready_accepts_existing_groups() -> None:
    client = FakeRedisStreamClient()
    client.group_error = ResponseError(
        "BUSYGROUP Consumer Group name already exists"
    )

    await RedisStreamTaskQueue(client).ensure_ready()

    assert len(client.group_calls) == 2


@pytest.mark.asyncio
async def test_ensure_ready_propagates_other_redis_errors() -> None:
    client = FakeRedisStreamClient()
    client.group_error = ResponseError("connection lost")

    with pytest.raises(ResponseError, match="connection lost"):
        await RedisStreamTaskQueue(client).ensure_ready()


@pytest.mark.asyncio
async def test_enqueue_routes_tasks_by_priority() -> None:
    client = FakeRedisStreamClient()
    queue = RedisStreamTaskQueue(client)

    await queue.enqueue(task(task_id="normal", priority=0))
    await queue.enqueue(task(task_id="large", priority=1))

    assert [entry[0] for entry in client.entries] == [
        "globex:intents",
        "globex:intents:large",
    ]
    payloads = [
        json.loads(entry[1]["payload"])
        for entry in client.entries
    ]
    assert [payload["task_id"] for payload in payloads] == [
        "normal",
        "large",
    ]
    assert payloads[0]["raw_query"] == "推荐一个通勤杯"
    assert [
        json.loads(client.values[f"globex:task:{task_id}"])[
            "state"
        ]
        for task_id in ("normal", "large")
    ] == ["queued", "queued"]


@pytest.mark.asyncio
async def test_status_round_trip_uses_one_hour_ttl() -> None:
    client = FakeRedisStreamClient()
    queue = RedisStreamTaskQueue(client)
    status = TaskStatus(
        task_id="task-001",
        shopping_session_id="session-001",
        buyer_id="buyer-001",
        state=TaskState.DONE,
        final_text="推荐结果",
    )

    await queue.set_status(status)
    restored = await queue.get_status("task-001")

    assert restored == status
    assert client.set_calls[0]["ex"] == 3600


@pytest.mark.asyncio
async def test_queued_status_reports_combined_lag() -> None:
    client = FakeRedisStreamClient()
    client.group_info = {
        "globex:intents": [
            {
                "name": b"globex-workers",
                "lag": 3,
                "pending": 1,
            }
        ],
        "globex:intents:large": [
            {
                "name": "globex-workers",
                "lag": None,
                "pending": 2,
            }
        ],
    }
    queue = RedisStreamTaskQueue(client)
    await queue.set_status(
        TaskStatus(
            task_id="task-001",
            shopping_session_id="session-001",
            buyer_id="buyer-001",
            state=TaskState.QUEUED,
        )
    )

    restored = await queue.get_status("task-001")

    assert restored is not None
    assert restored.queue_position == 5


@pytest.mark.asyncio
async def test_missing_or_invalid_status_is_a_miss() -> None:
    client = FakeRedisStreamClient()
    queue = RedisStreamTaskQueue(client)

    assert await queue.get_status("missing") is None

    client.values["globex:task:broken-json"] = "not-json"
    client.values["globex:task:wrong-shape"] = "[]"
    client.values["globex:task:bad-state"] = json.dumps(
        {
            "task_id": "bad-state",
            "state": "unknown",
        }
    )

    assert await queue.get_status("broken-json") is None
    assert await queue.get_status("wrong-shape") is None
    assert await queue.get_status("bad-state") is None


@pytest.mark.asyncio
async def test_depth_failure_does_not_break_health_checks() -> None:
    client = FakeRedisStreamClient()
    client.info_errors = {
        "globex:intents",
        "globex:intents:large",
    }

    assert await RedisStreamTaskQueue(client).depth() == 0


@pytest.mark.asyncio
async def test_consume_handles_and_acknowledges_a_new_task() -> None:
    client = FakeRedisStreamClient()
    payload = json.dumps(
        task().to_dict(),
        ensure_ascii=False,
    )
    client.read_results = [
        [
            (
                b"globex:intents",
                [
                    (
                        b"1-0",
                        {b"payload": payload.encode("utf-8")},
                    )
                ],
            )
        ]
    ]
    stopped = False
    handled: list[IntentTask] = []

    async def handler(intent_task: IntentTask) -> None:
        nonlocal stopped
        handled.append(intent_task)
        stopped = True

    await RedisStreamTaskQueue(client).consume(
        consumer_name="worker-1",
        handler=handler,
        should_stop=lambda: stopped,
    )

    assert [item.task_id for item in handled] == ["task-001"]
    assert client.acked == [
        (
            "globex:intents",
            "globex-workers",
            "1-0",
        )
    ]
    assert len(client.claim_calls) == 2


@pytest.mark.asyncio
async def test_failed_task_stays_pending_before_retry_limit() -> None:
    client = FakeRedisStreamClient()
    client.delivery_counts["1-0"] = 1
    queue = RedisStreamTaskQueue(client)

    async def failing_handler(_: IntentTask) -> None:
        raise RuntimeError("model unavailable")

    await queue._handle_one(
        stream="globex:intents",
        message_id="1-0",
        fields={
            "payload": json.dumps(task().to_dict()),
        },
        handler=failing_handler,
        max_deliveries=3,
    )

    assert client.acked == []
    assert client.entries == []
    status = await queue.get_status("task-001")
    assert status is not None
    assert status.state is TaskState.RETRYING
    assert status.error == "model unavailable"


@pytest.mark.asyncio
async def test_failed_task_moves_to_dead_letter_at_limit() -> None:
    client = FakeRedisStreamClient()
    client.delivery_counts["1-0"] = 3
    queue = RedisStreamTaskQueue(client)

    async def failing_handler(_: IntentTask) -> None:
        raise RuntimeError("model unavailable")

    await queue._handle_one(
        stream="globex:intents",
        message_id="1-0",
        fields={
            "payload": json.dumps(task().to_dict()),
        },
        handler=failing_handler,
        max_deliveries=3,
    )

    assert client.acked == [
        (
            "globex:intents",
            "globex-workers",
            "1-0",
        )
    ]
    dead_stream, dead_fields = client.entries[0]
    assert dead_stream == "globex:intents:dead"
    assert dead_fields["reason"] == "model unavailable"
    assert dead_fields["source_stream"] == "globex:intents"
    status = await queue.get_status("task-001")
    assert status is not None
    assert status.state is TaskState.FAILED


@pytest.mark.asyncio
async def test_invalid_payload_moves_directly_to_dead_letter() -> None:
    client = FakeRedisStreamClient()
    queue = RedisStreamTaskQueue(client)
    handler_called = False

    async def handler(_: IntentTask) -> None:
        nonlocal handler_called
        handler_called = True

    await queue._handle_one(
        stream="globex:intents",
        message_id="broken-0",
        fields={"payload": "not-json"},
        handler=handler,
        max_deliveries=3,
    )

    assert handler_called is False
    assert client.entries[0][0] == "globex:intents:dead"
    assert client.acked == [
        (
            "globex:intents",
            "globex-workers",
            "broken-0",
        )
    ]


@pytest.mark.asyncio
async def test_read_prefers_normal_stream() -> None:
    client = FakeRedisStreamClient()
    client.read_results = [
        [("globex:intents", [])],
    ]
    queue = RedisStreamTaskQueue(client)

    await queue._read_new_tasks(
        consumer_name="worker-1",
        count=2,
    )

    assert len(client.read_calls) == 1
    assert client.read_calls[0]["streams"] == {
        "globex:intents": ">",
    }


@pytest.mark.asyncio
async def test_read_large_stream_when_normal_is_empty() -> None:
    client = FakeRedisStreamClient()
    client.read_results = [
        [],
        [("globex:intents:large", [])],
    ]
    queue = RedisStreamTaskQueue(client)

    await queue._read_new_tasks(
        consumer_name="worker-1",
        count=2,
    )

    assert [call["streams"] for call in client.read_calls] == [
        {"globex:intents": ">"},
        {"globex:intents:large": ">"},
    ]


@pytest.mark.asyncio
async def test_claim_stale_tasks_uses_idle_time_and_capacity() -> None:
    client = FakeRedisStreamClient()
    normal_entry = (
        "1-0",
        {"payload": json.dumps(task(task_id="normal").to_dict())},
    )
    large_entry = (
        "2-0",
        {
            "payload": json.dumps(
                task(task_id="large", priority=1).to_dict()
            )
        },
    )
    client.claim_results = {
        "globex:intents": ["0-0", [normal_entry], []],
        "globex:intents:large": ["0-0", [large_entry], []],
    }

    batches = await RedisStreamTaskQueue(
        client
    )._claim_stale_tasks(
        consumer_name="worker-1",
        count=2,
    )

    assert batches == [
        ("globex:intents", [normal_entry]),
        ("globex:intents:large", [large_entry]),
    ]
    assert [call["count"] for call in client.claim_calls] == [
        2,
        1,
    ]
    assert all(
        call["groupname"] == "globex-workers"
        and call["consumername"] == "worker-1"
        and call["min_idle_time"] == 60_000
        and call["start_id"] == "0-0"
        for call in client.claim_calls
    )


@pytest.mark.asyncio
async def test_claim_failure_on_one_stream_checks_the_other() -> None:
    client = FakeRedisStreamClient()
    client.claim_errors.add("globex:intents")
    large_entry = (
        "2-0",
        {
            "payload": json.dumps(
                task(task_id="large", priority=1).to_dict()
            )
        },
    )
    client.claim_results["globex:intents:large"] = [
        "0-0",
        [large_entry],
        [],
    ]

    batches = await RedisStreamTaskQueue(
        client
    )._claim_stale_tasks(
        consumer_name="worker-1",
        count=1,
    )

    assert batches == [
        ("globex:intents:large", [large_entry])
    ]


@pytest.mark.asyncio
async def test_claim_continues_from_returned_cursor() -> None:
    client = FakeRedisStreamClient()
    claimed_entry = (
        "1-0",
        {"payload": json.dumps(task().to_dict())},
    )
    client.claim_results["globex:intents"] = [
        "9-0",
        [claimed_entry],
        [],
    ]
    queue = RedisStreamTaskQueue(client)

    await queue._claim_stale_tasks(
        consumer_name="worker-1",
        count=1,
    )
    client.claim_results["globex:intents"] = [
        "0-0",
        [claimed_entry],
        [],
    ]
    await queue._claim_stale_tasks(
        consumer_name="worker-1",
        count=1,
    )

    normal_calls = [
        call
        for call in client.claim_calls
        if call["name"] == "globex:intents"
    ]
    assert [call["start_id"] for call in normal_calls] == [
        "0-0",
        "9-0",
    ]
    assert queue._claim_cursors["globex:intents"] == "0-0"


@pytest.mark.asyncio
async def test_consume_processes_claimed_task_before_new_task() -> None:
    client = FakeRedisStreamClient()
    claimed_entry = (
        b"1-0",
        {
            b"payload": json.dumps(
                task(task_id="recovered").to_dict()
            ).encode("utf-8")
        },
    )
    client.claim_results["globex:intents"] = [
        b"0-0",
        [claimed_entry],
        [],
    ]
    stopped = False
    handled: list[str] = []

    async def handler(intent_task: IntentTask) -> None:
        nonlocal stopped
        handled.append(intent_task.task_id)
        stopped = True

    await RedisStreamTaskQueue(client).consume(
        consumer_name="worker-1",
        handler=handler,
        should_stop=lambda: stopped,
    )

    assert handled == ["recovered"]
    assert client.read_calls == []
    assert client.acked == [
        (
            "globex:intents",
            "globex-workers",
            "1-0",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_deliveries", "concurrency"),
    [
        (0, 1),
        (1, 0),
    ],
)
async def test_consume_rejects_invalid_limits(
    max_deliveries: int,
    concurrency: int,
) -> None:
    queue = RedisStreamTaskQueue(FakeRedisStreamClient())

    with pytest.raises(ValueError):
        await queue.consume(
            consumer_name="worker-1",
            handler=lambda _: None,
            should_stop=lambda: True,
            max_deliveries=max_deliveries,
            concurrency=concurrency,
        )
