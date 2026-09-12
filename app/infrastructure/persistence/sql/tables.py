from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


AutoPrimaryKey = BigInteger().with_variant(
    Integer,
    "sqlite",
)


class Base(DeclarativeBase):
    pass


class ConversationSessionRow(Base):
    """
    The table for all sessions.
    For example:
    conversation_sessions

    session_id    buyer_id    locale    currency ...
    ------------------------------------------------
    session-001   buyer-001   zh-CN     CNY ...
    """
    __tablename__ = "conversation_sessions"

    session_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )
    buyer_id: Mapped[str] = mapped_column(
        String(128),
        index=True,
    )
    locale: Mapped[str] = mapped_column(
        String(16),
    )
    currency: Mapped[str] = mapped_column(
        String(8),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConversationMessageRow(Base):
    """
    The table of chat history.
    For example:
    id  session_id   turn_index  role    content
    ------------------------------------------------------
    1   session-001  0           buyer   我想买旅行装备
    2   session-001  1           agent   你的预算是多少？
    3   session-001  2           buyer   300元
    4   session-001  3           agent   我推荐……
    """
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(
        AutoPrimaryKey,
        primary_key=True,
        autoincrement=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("conversation_sessions.session_id"),
    )
    turn_index: Mapped[int] = mapped_column(
        Integer,
    )
    buyer_id: Mapped[str] = mapped_column(
        String(128),
    )
    role: Mapped[str] = mapped_column(
        String(16),
    )
    content: Mapped[str] = mapped_column(
        Text,
    )
    model: Mapped[str] = mapped_column(
        String(128),
        default="",
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "turn_index",
            name="uq_conversation_message_turn",
        ),
        Index(
            "ix_conversation_message_session_turn",
            "session_id",
            "turn_index",
        ),
    )


class ConversationEventRow(Base):
    """
    The table of events happened in a conversation.
    For example:
    id  session_id   type          payload
    ------------------------------------------------
    1   session-001  tool.invoke   {...}
    2   session-001  tool.result   {...}
    3   session-001  final.result  {...}
    """
    __tablename__ = "conversation_events"

    id: Mapped[int] = mapped_column(
        AutoPrimaryKey,
        primary_key=True,
        autoincrement=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("conversation_sessions.session_id"),
        index=True,
    )
    type: Mapped[str] = mapped_column(
        String(64),
    )
    payload: Mapped[dict] = mapped_column(
        JSON,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )


class AgentSessionStateRow(Base):
    """
    The table of AgentStates in json.
    """
    __tablename__ = "agent_session_states"

    session_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )
    snapshot_json: Mapped[str] = mapped_column(
        Text,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
