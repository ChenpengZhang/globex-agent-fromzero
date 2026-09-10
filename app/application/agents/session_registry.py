import asyncio
import json
import logging
from dataclasses import dataclass, field

from agentscope.agent import Agent
from agentscope.state import AgentState

from app.application.agents.main_agent import (
    MainAgentFactory,
)
from app.domain.session.ports.session_store import (
    SessionStore,
)


logger = logging.getLogger(__name__)


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
        session_store: SessionStore,
    ) -> None:
        self._main_agent_factory = main_agent_factory
        self._session_store = session_store
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
            # Prevent two requests A,B from creating the same session
            # wait until the first session A has done creating
            existing = self._sessions.get(
                shopping_session_id,
            )
            # get the session created by A

            if existing is not None:
                self._ensure_owner(
                    session=existing,
                    buyer_id=buyer_id,
                )
                return existing  # return cached session

            restored_state = await self._restore(
                shopping_session_id=shopping_session_id,
                buyer_id=buyer_id,
            )  # restore ssssion or create new one

            session = SessionEntry(
                shopping_session_id=shopping_session_id,
                buyer_id=buyer_id,
                agent=self._main_agent_factory.build(
                    state=restored_state,
                ),
            )

            self._sessions[
                shopping_session_id
            ] = session

            return session

    async def persist(
        self,
        shopping_session_id: str,
    ) -> None:
        """save the current AgentState and session owner"""
        session = self._sessions.get(
            shopping_session_id,
        )

        if session is None:
            return

        try:
            snapshot_json = json.dumps(
                {
                    "buyer_id": session.buyer_id,
                    "state_json": (
                        session.agent.state.model_dump_json()
                    ),
                },
                ensure_ascii=False,
            )
            await self._session_store.save(
                shopping_session_id,
                snapshot_json,
            )
        except Exception as error:
            logger.warning(
                "会话状态保存失败：%s（%s）",
                shopping_session_id,
                error,
            )

    async def _restore(
        self,
        shopping_session_id: str,
        buyer_id: str,
    ) -> AgentState | None:
        try:
            snapshot_json = await self._session_store.load(
                shopping_session_id,
            )
        except Exception as error:
            logger.warning(
                "会话状态读取失败，创建新会话：%s（%s）",
                shopping_session_id,
                error,
            )
            return None

        if snapshot_json is None:
            return None

        try:
            snapshot = json.loads(snapshot_json)
            stored_buyer_id = snapshot["buyer_id"]

            if stored_buyer_id != buyer_id:
                raise SessionOwnershipError(
                    "该 shopping_session_id "
                    "已绑定到其他 buyer",
                )

            return AgentState.model_validate_json(
                snapshot["state_json"],
            )

        except SessionOwnershipError:
            raise

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            logger.warning(
                "会话快照损坏，创建新会话：%s（%s）",
                shopping_session_id,
                error,
            )
            return None
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
    