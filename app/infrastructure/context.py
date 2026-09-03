from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class ShoppingContextSnapshot:
    shopping_session_id: str
    buyer_id: str
    locale: str
    currency: str


_current_snapshot: ContextVar[
    ShoppingContextSnapshot | None
] = ContextVar(
    "globex_shopping_context",
    default=None,
)


class ShoppingContext:
    @staticmethod
    def set(
        snapshot: ShoppingContextSnapshot,
    ) -> Token[ShoppingContextSnapshot | None]:
        return _current_snapshot.set(snapshot)

    @staticmethod
    def reset(
        token: Token[ShoppingContextSnapshot | None],
    ) -> None:
        _current_snapshot.reset(token)

    @staticmethod
    def current() -> ShoppingContextSnapshot | None:
        return _current_snapshot.get()

    @staticmethod
    def require_current() -> ShoppingContextSnapshot:
        snapshot = _current_snapshot.get()

        if snapshot is None:
            raise RuntimeError(
                "当前请求缺少 ShoppingContext"
            )

        return snapshot