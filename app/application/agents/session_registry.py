import asyncio
from dataclasses import dataclass, field

from agentscope.agent import Agent

from app.application.agents.main_agent import (
    MainAgentFactory,
)


class SessionOwnershipError(ValueError):
    """Raised when a session is reused by another buyer."""


@dataclass
class SessionEntry:
    shopping_session_id: str
    buyer_id: str
    agent: Agent
    execution_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
    )


class SessionRegistry:
    def __init__(
        self,
        main_agent_factory: MainAgentFactory,
    ) -> None:
        self._main_agent_factory = main_agent_factory
        self._sessions: dict[str, SessionEntry] = {}
        self._creation_lock = asyncio.Lock()

    async def get_or_create(
        self,
        shopping_session_id: str,
        buyer_id: str,
    ) -> SessionEntry:
        existing = self._sessions.get(
            shopping_session_id,
        )

        if existing is not None:
            self._ensure_owner(
                session=existing,
                buyer_id=buyer_id,
            )
            return existing

        async with self._creation_lock:
            # Prevent two requests from creating the same session
            existing = self._sessions.get(
                shopping_session_id,
            )

            if existing is not None:
                self._ensure_owner(
                    session=existing,
                    buyer_id=buyer_id,
                )
                return existing

            session = SessionEntry(
                shopping_session_id=shopping_session_id,
                buyer_id=buyer_id,
                agent=self._main_agent_factory.build(),
            )

            self._sessions[
                shopping_session_id
            ] = session

            return session

    @staticmethod
    def _ensure_owner(
        session: SessionEntry,
        buyer_id: str,
    ) -> None:
        if session.buyer_id != buyer_id:
            raise SessionOwnershipError(
                "该 shopping_session_id "
                "已绑定到其他 buyer",
            )

    def __len__(self) -> int:
        return len(self._sessions)
    