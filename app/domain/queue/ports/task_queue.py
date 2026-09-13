from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class IntentTask:
    """A mission list to give to the worker"""

    task_id: str
    shopping_session_id: str
    buyer_id: str
    locale: str
    currency: str
    raw_query: str
    enqueued_at: str = field(default_factory=_now_iso)
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("IntentTask.task_id cannot be empty")

        if not self.shopping_session_id.strip():
            raise ValueError(
                "IntentTask.shopping_session_id cannot be empty"
            )

        if not self.buyer_id.strip():
            raise ValueError(
                "IntentTask.buyer_id cannot be empty"
            )

        if not self.raw_query.strip():
            raise ValueError(
                "IntentTask.raw_query cannot be empty"
            )

        currency = self.currency.strip().upper()

        if len(currency) != 3:
            raise ValueError(
                "IntentTask.currency must have three characters"
            )

        if self.priority < 0:
            raise ValueError(
                "IntentTask.priority cannot be negative"
            )

        object.__setattr__(self, "task_id", self.task_id.strip())
        object.__setattr__(
            self,
            "shopping_session_id",
            self.shopping_session_id.strip(),
        )
        object.__setattr__(
            self,
            "buyer_id",
            self.buyer_id.strip(),
        )
        object.__setattr__(
            self,
            "locale",
            self.locale.strip() or "zh-CN",
        )
        object.__setattr__(self, "currency", currency)
        object.__setattr__(
            self,
            "raw_query",
            self.raw_query.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "shopping_session_id": self.shopping_session_id,
            "buyer_id": self.buyer_id,
            "locale": self.locale,
            "currency": self.currency,
            "raw_query": self.raw_query,
            "enqueued_at": self.enqueued_at,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
    ) -> "IntentTask":
        return cls(
            task_id=raw["task_id"],
            shopping_session_id=raw[
                "shopping_session_id"
            ],
            buyer_id=raw["buyer_id"],
            locale=raw.get("locale", "zh-CN"),
            currency=raw.get("currency", "CNY"),
            raw_query=raw["raw_query"],
            enqueued_at=(
                raw.get("enqueued_at")
                or _now_iso()
            ),
            priority=int(raw.get("priority", 0)),
        )


@dataclass(frozen=True)
class TaskStatus:
    """Current observable state of an asynchronous task."""

    task_id: str
    shopping_session_id: str
    buyer_id: str
    state: TaskState | str
    final_text: str = ""
    error: str = ""
    queue_position: int = 0

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("TaskStatus.task_id cannot be empty")

        if not self.shopping_session_id.strip():
            raise ValueError(
                "TaskStatus.shopping_session_id cannot be empty"
            )

        if not self.buyer_id.strip():
            raise ValueError(
                "TaskStatus.buyer_id cannot be empty"
            )

        try:
            state = TaskState(self.state)
        except ValueError as error:
            raise ValueError(
                f"Unsupported task state: {self.state}"
            ) from error

        if self.queue_position < 0:
            raise ValueError(
                "TaskStatus.queue_position cannot be negative"
            )

        object.__setattr__(self, "task_id", self.task_id.strip())
        object.__setattr__(
            self,
            "shopping_session_id",
            self.shopping_session_id.strip(),
        )
        object.__setattr__(
            self,
            "buyer_id",
            self.buyer_id.strip(),
        )
        object.__setattr__(self, "state", state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "shopping_session_id": self.shopping_session_id,
            "buyer_id": self.buyer_id,
            "state": self.state.value,
            "final_text": self.final_text,
            "error": self.error,
            "queue_position": self.queue_position,
        }

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
    ) -> "TaskStatus":
        return cls(
            task_id=raw["task_id"],
            shopping_session_id=raw[
                "shopping_session_id"
            ],
            buyer_id=raw["buyer_id"],
            state=raw["state"],
            final_text=raw.get("final_text", ""),
            error=raw.get("error", ""),
            queue_position=int(
                raw.get("queue_position", 0)
            ),
        )


TaskHandler = Callable[[IntentTask], Awaitable[None]]
StopPredicate = Callable[[], bool]


class TaskQueue(ABC):
    """Application-facing boundary for background task delivery."""

    @abstractmethod
    async def ensure_ready(self) -> None:
        """Create any queue resources required by the adapter."""

    @abstractmethod
    async def enqueue(self, task: IntentTask) -> None:
        """Atomically add a task and initialize its queued status."""

    @abstractmethod
    async def set_status(
        self,
        status: TaskStatus,
    ) -> None:
        """Persist the current task status."""

    @abstractmethod
    async def get_status(
        self,
        task_id: str,
    ) -> TaskStatus | None:
        """Return the task status when it still exists."""

    @abstractmethod
    async def depth(self) -> int:
        """Return the approximate number of waiting tasks."""

    @abstractmethod
    async def consume(
        self,
        consumer_name: str,
        handler: TaskHandler,
        should_stop: StopPredicate,
        max_deliveries: int = 3,
        concurrency: int = 1,
    ) -> None:
        """Consume tasks until shutdown is requested."""
