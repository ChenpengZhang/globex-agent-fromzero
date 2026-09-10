from abc import ABC, abstractmethod


class SessionStore(ABC):
    """Interface for Agent conversation state storage"""

    @abstractmethod
    async def save(
        self,
        session_id: str,
        state_json: str,
    ) -> None:
        """The JSON snapshot of the AgentState"""

    @abstractmethod
    async def load(
        self,
        session_id: str,
    ) -> str | None:
        """Read AgentState JSON snapshot or return None"""
        