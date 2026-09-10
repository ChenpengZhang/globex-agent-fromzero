from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationTurnOutput:
    role: str
    content: str
    model: str
    latency_ms: int
    created_at: str


@dataclass(frozen=True)
class ConversationHistoryOutput:
    session_id: str
    turns: list[ConversationTurnOutput]
    