import asyncio
import logging
import os
import signal
import socket
import uuid

from app.application.agents.orchestrator import (
    SubmitIntentInput,
)
from app.application.events import TradeEventType
from app.composition import Container, build_container
from app.domain.queue.ports.task_queue import (
    IntentTask,
    TaskState,
    TaskStatus,
)


logger = logging.getLogger(__name__)


async def process_task(
    container: Container,
    task: IntentTask,
) -> None:
    """Execute one queued intent and persist its visible status."""

    task_queue = container.task_queue

    if task_queue is None:
        raise RuntimeError("Task queue is unavailable")

    await task_queue.set_status(
        TaskStatus(
            task_id=task.task_id,
            shopping_session_id=task.shopping_session_id,
            buyer_id=task.buyer_id,
            state=TaskState.RUNNING,
        )
    )
    container.event_bus.publish(
        task.shopping_session_id,
        TradeEventType.TASK_STARTED,
        {"task_id": task.task_id},
    )

    result = await container.orchestrator.handle_intent(
        SubmitIntentInput(
            shopping_session_id=task.shopping_session_id,
            buyer_id=task.buyer_id,
            locale=task.locale,
            currency=task.currency,
            raw_query=task.raw_query,
        )
    )

    await task_queue.set_status(
        TaskStatus(
            task_id=task.task_id,
            shopping_session_id=task.shopping_session_id,
            buyer_id=task.buyer_id,
            state=TaskState.DONE,
            final_text=result.final_text,
        )
    )


async def run_worker() -> None:
    """Run queued intents until the process receives a stop signal."""

    container = build_container()
    task_queue = container.task_queue

    if task_queue is None:
        raise RuntimeError(
            "Task queue is disabled; configure REDIS_URL and "
            "QUEUE_ENABLED before starting the worker"
        )

    consumer_name = (
        f"{socket.gethostname()}-{os.getpid()}-"
        f"{uuid.uuid4().hex[:6]}"
    )
    stopping = asyncio.Event()

    def request_stop() -> None:
        if not stopping.is_set():
            logger.info(
                "Stop requested; waiting for active tasks to finish"
            )
            stopping.set()

    loop = asyncio.get_running_loop()

    for process_signal in (
        signal.SIGTERM,
        signal.SIGINT,
    ):
        loop.add_signal_handler(
            process_signal,
            request_stop,
        )

    logger.info(
        "Starting worker %s with concurrency %d",
        consumer_name,
        container.settings.worker_concurrency,
    )

    await container.startup()

    try:
        await task_queue.consume(
            consumer_name=consumer_name,
            handler=lambda task: process_task(
                container,
                task,
            ),
            should_stop=stopping.is_set,
            max_deliveries=(
                container.settings.queue_max_deliveries
            ),
            concurrency=container.settings.worker_concurrency,
        )
    finally:
        logger.info("Stopping worker %s", consumer_name)
        await container.shutdown()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)s "
            "%(name)s %(message)s"
        ),
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
