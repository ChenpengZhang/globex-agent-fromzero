import asyncio
import json
import logging
from typing import Any

from redis.exceptions import ResponseError

from app.domain.queue.ports.task_queue import (
    IntentTask,
    StopPredicate,
    TaskHandler,
    TaskQueue,
    TaskState,
    TaskStatus,
)


logger = logging.getLogger(__name__)

_NORMAL_STREAM = "globex:intents"
_LARGE_STREAM = "globex:intents:large"
_CONSUMER_GROUP = "globex-workers"
_STATUS_PREFIX = "globex:task:"
_STATUS_TTL_SECONDS = 60 * 60
_DEAD_LETTER_STREAM = "globex:intents:dead"
_READ_BLOCK_MS = 1000
_CLAIM_IDLE_MS = 60 * 1000


class RedisStreamTaskQueue(TaskQueue):
    """Redis Stream implementation of the task queue boundary."""

    def __init__(
        self,
        client: Any,
    ) -> None:
        self._client = client
        self._claim_cursors = {
            _NORMAL_STREAM: "0-0",
            _LARGE_STREAM: "0-0",
        }

    async def ensure_ready(self) -> None:
        """
        Idempotently create both streams and their consumer groups.

        Redis creates the stream automatically when mkstream is true.
        BUSYGROUP means another process has already created the group.
        """

        for stream in (
            _NORMAL_STREAM,
            _LARGE_STREAM,
        ):
            try:
                await self._client.xgroup_create(
                    name=stream,
                    groupname=_CONSUMER_GROUP,
                    id="0",
                    mkstream=True,
                )
            except ResponseError as error:
                if "BUSYGROUP" not in str(error):
                    raise

    async def enqueue(
        self,
        task: IntentTask,
    ) -> None:
        stream = (
            _LARGE_STREAM
            if task.priority > 0
            else _NORMAL_STREAM
        )
        #  allocate to different streams based on priority

        payload = json.dumps(
            task.to_dict(),
            ensure_ascii=False,
        )
        queued_status = json.dumps(
            TaskStatus(
                task_id=task.task_id,
                shopping_session_id=task.shopping_session_id,
                buyer_id=task.buyer_id,
                state=TaskState.QUEUED,
            ).to_dict(),
            ensure_ascii=False,
        )

        async with self._client.pipeline(
            transaction=True,
        ) as pipeline:
            pipeline.xadd(
                stream,
                {"payload": payload},
            )
            pipeline.set(
                f"{_STATUS_PREFIX}{task.task_id}",
                queued_status,
                ex=_STATUS_TTL_SECONDS,
            )
            await pipeline.execute()

    async def set_status(
        self,
        status: TaskStatus,
    ) -> None:
        await self._client.set(
            f"{_STATUS_PREFIX}{status.task_id}",
            json.dumps(
                status.to_dict(),
                ensure_ascii=False,
            ),
            ex=_STATUS_TTL_SECONDS,
        )

    async def get_status(
        self,
        task_id: str,
    ) -> TaskStatus | None:
        raw = await self._client.get(
            f"{_STATUS_PREFIX}{task_id}"
        )

        if raw is None:
            return None

        try:
            data = json.loads(raw)

            if not isinstance(data, dict):
                return None

            state = TaskState(data["state"])
            queue_position = (
                await self.depth()
                if state is TaskState.QUEUED
                else 0
            )

            return TaskStatus.from_dict(
                {
                    **data,
                    "queue_position": queue_position,
                }
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            logger.warning(
                "Invalid task status payload: %s (%s)",
                task_id,
                error,
            )
            return None

    async def depth(self) -> int:
        """
        Return the combined consumer-group lag.

        This value is approximate and intended for health reporting,
        not as an exact position for a particular task.
        """

        total = 0

        for stream in (
            _NORMAL_STREAM,
            _LARGE_STREAM,
        ):
            total += await self._stream_depth(stream)

        return total

    async def _stream_depth(
        self,
        stream: str,
    ) -> int:
        try:
            groups = await self._client.xinfo_groups(
                stream
            )
        except Exception as error:
            logger.warning(
                "Queue depth lookup failed: %s (%s)",
                stream,
                error,
            )
            return 0

        for group in groups:
            name = group.get("name")

            if isinstance(name, bytes):
                name = name.decode("utf-8")

            if name != _CONSUMER_GROUP:
                continue

            lag = group.get("lag")

            if lag is not None:
                return int(lag)

            return int(group.get("pending", 0))

        return 0

    async def consume(
        self,
        consumer_name: str,
        handler: TaskHandler,
        should_stop: StopPredicate,
        max_deliveries: int = 3,
        concurrency: int = 1,
    ) -> None:
        """Consume new tasks until shutdown is requested."""

        if max_deliveries < 1:
            raise ValueError(
                "max_deliveries must be at least 1"
            )

        if concurrency < 1:
            raise ValueError(
                "concurrency must be at least 1"
            )

        await self.ensure_ready()

        in_flight: set[asyncio.Task[None]] = set()

        while not should_stop():
            completed = {
                task
                for task in in_flight
                if task.done()
            }

            if completed:
                await asyncio.gather(
                    *completed,
                    return_exceptions=True,
                )
                in_flight.difference_update(completed)

            free_slots = concurrency - len(in_flight)

            if free_slots <= 0:
                completed, _ = await asyncio.wait(
                    in_flight,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                await asyncio.gather(
                    *completed,
                    return_exceptions=True,
                )
                in_flight.difference_update(completed)
                continue

            try:
                batches = await self._claim_stale_tasks(
                    consumer_name=consumer_name,
                    count=free_slots,
                )

                if not batches:
                    batches = await self._read_new_tasks(
                        consumer_name=consumer_name,
                        count=free_slots,
                    )
            except Exception as error:
                logger.warning(
                    "Queue read failed; retrying: %s",
                    error,
                )
                await asyncio.sleep(1)
                continue

            if not batches:
                continue

            for raw_stream, entries in batches:
                stream = self._as_text(raw_stream)

                for raw_message_id, fields in entries:
                    message_id = self._as_text(
                        raw_message_id
                    )

                    running = asyncio.create_task(
                        self._handle_one(
                            stream=stream,
                            message_id=message_id,
                            fields=fields,
                            handler=handler,
                            max_deliveries=max_deliveries,
                        )
                    )
                    in_flight.add(running)

        if in_flight:
            await asyncio.gather(
                *in_flight,
                return_exceptions=True,
            )

    async def _claim_stale_tasks(
        self,
        consumer_name: str,
        count: int,
    ) -> list:
        """
        Claim tasks left pending by failed or stopped workers.

        A task must remain idle for at least one minute before another
        delivery attempt, preventing immediate tight retry loops.
        """

        batches = []
        remaining = count

        for stream in (
            _NORMAL_STREAM,
            _LARGE_STREAM,
        ):
            if remaining <= 0:
                break

            try:
                result = await self._client.xautoclaim(
                    name=stream,
                    groupname=_CONSUMER_GROUP,
                    consumername=consumer_name,
                    min_idle_time=_CLAIM_IDLE_MS,
                    start_id=self._claim_cursors[stream],
                    count=remaining,
                )
            except Exception as error:
                logger.warning(
                    "Pending task claim failed: %s (%s)",
                    stream,
                    error,
                )
                continue

            if (
                not isinstance(result, (list, tuple))
                or len(result) < 2
            ):
                continue

            self._claim_cursors[stream] = self._as_text(
                result[0]
            )

            entries = result[1]

            if not entries:
                continue

            batches.append((stream, entries))
            remaining -= len(entries)

        return batches

    async def _read_new_tasks(
        self,
        consumer_name: str,
        count: int,
    ) -> list:
        """
        Prefer normal tasks and read the large stream when it is idle.

        Reading one stream at a time keeps the concurrency limit exact.
        """

        normal_batches = await self._client.xreadgroup(
            groupname=_CONSUMER_GROUP,
            consumername=consumer_name,
            streams={
                _NORMAL_STREAM: ">",
            },
            count=count,
            block=100,
        )

        if normal_batches:
            return normal_batches

        return await self._client.xreadgroup(
            groupname=_CONSUMER_GROUP,
            consumername=consumer_name,
            streams={
                _LARGE_STREAM: ">",
            },
            count=count,
            block=_READ_BLOCK_MS,
        )

    async def _handle_one(
        self,
        stream: str,
        message_id: str,
        fields: dict,
        handler: TaskHandler,
        max_deliveries: int,
    ) -> None:
        raw_payload = fields.get("payload")

        if raw_payload is None:
            raw_payload = fields.get(b"payload")

        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")

        if not isinstance(raw_payload, str):
            await self._move_to_dead_letter(
                stream=stream,
                message_id=message_id,
                payload="",
                reason="Missing task payload",
            )
            return

        try:
            decoded = json.loads(raw_payload)

            if not isinstance(decoded, dict):
                raise ValueError(
                    "Task payload must be a JSON object"
                )

            task = IntentTask.from_dict(decoded)
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            await self._move_to_dead_letter(
                stream=stream,
                message_id=message_id,
                payload=raw_payload,
                reason=str(error),
            )
            return

        try:
            await handler(task)
        except Exception as error:
            deliveries = await self._delivery_count(
                stream=stream,
                message_id=message_id,
            )

            if deliveries >= max_deliveries:
                await self.set_status(
                    TaskStatus(
                        task_id=task.task_id,
                        shopping_session_id=(
                            task.shopping_session_id
                        ),
                        buyer_id=task.buyer_id,
                        state=TaskState.FAILED,
                        error=str(error),
                    )
                )

                await self._move_to_dead_letter(
                    stream=stream,
                    message_id=message_id,
                    payload=raw_payload,
                    reason=str(error),
                )
            else:
                await self.set_status(
                    TaskStatus(
                        task_id=task.task_id,
                        shopping_session_id=(
                            task.shopping_session_id
                        ),
                        buyer_id=task.buyer_id,
                        state=TaskState.RETRYING,
                        error=str(error),
                    )
                )

                logger.warning(
                    "Task processing failed on delivery %d: "
                    "%s (%s)",
                    deliveries,
                    task.task_id,
                    error,
                )

            return

        await self._client.xack(
            stream,
            _CONSUMER_GROUP,
            message_id,
        )

    async def _delivery_count(
        self,
        stream: str,
        message_id: str,
    ) -> int:
        try:
            pending = await self._client.xpending_range(
                name=stream,
                groupname=_CONSUMER_GROUP,
                min=message_id,
                max=message_id,
                count=1,
            )
        except Exception as error:
            logger.warning(
                "Delivery count lookup failed: %s (%s)",
                message_id,
                error,
            )
            return 1

        if not pending:
            return 1

        value = pending[0].get("times_delivered")

        if value is None:
            value = pending[0].get(
                b"times_delivered",
                1,
            )

        return int(value)

    async def _move_to_dead_letter(
        self,
        stream: str,
        message_id: str,
        payload: str,
        reason: str,
    ) -> None:
        await self._client.xadd(
            _DEAD_LETTER_STREAM,
            {
                "payload": payload,
                "reason": reason,
                "source_stream": stream,
                "source_message_id": message_id,
            },
        )

        await self._client.xack(
            stream,
            _CONSUMER_GROUP,
            message_id,
        )

        logger.error(
            "Task moved to dead-letter stream: %s (%s)",
            message_id,
            reason,
        )

    @staticmethod
    def _as_text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")

        return str(value)
