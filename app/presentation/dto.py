from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.domain.queue.ports.task_queue import TaskState


class SubmitIntentRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    shopping_session_id: str | None = Field(
        default=None,
        min_length=1,
    )
    buyer_id: str = Field(
        min_length=1,
    )
    locale: str = Field(
        default="zh-CN",
        min_length=1,
    )
    currency: str = Field(
        default="CNY",
        min_length=3,
        max_length=3,
    )
    raw_query: str = Field(
        min_length=1,
    )
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(
        cls,
        value: str,
    ) -> str:
        return value.upper()


class SubmitIntentResponse(BaseModel):
    shopping_session_id: str
    final_text: str


class AsyncSubmitIntentResponse(BaseModel):
    shopping_session_id: str
    task_id: str
    state: TaskState


class TaskStatusResponse(BaseModel):
    task_id: str
    shopping_session_id: str
    state: TaskState
    final_text: str
    error: str
    queue_position: int


class ConversationTurnResponse(BaseModel):
    role: str
    content: str
    model: str
    latency_ms: int
    created_at: str


class ConversationHistoryResponse(BaseModel):
    session_id: str
    turns: list[ConversationTurnResponse]
