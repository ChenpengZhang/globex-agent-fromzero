from abc import ABC, abstractmethod

from app.domain.buyer.preference import (
    BuyerPreference,
)


class PreferenceStore(ABC):
    """Persistence boundary for durable buyer preferences."""

    @abstractmethod
    async def append(
        self,
        preference: BuyerPreference,
    ) -> None:
        """
        Store one preference idempotently.

        The identity is buyer_id, kind, and statement.
        """

    @abstractmethod
    async def list_by_buyer(
        self,
        buyer_id: str,
    ) -> list[BuyerPreference]:
        """Return one buyer's preferences in write order."""

    @abstractmethod
    async def delete(
        self,
        buyer_id: str,
        statement: str,
    ) -> bool:
        """
        Delete preferences by exact statement.

        All kinds with the same statement are removed.
        Return whether any preference was deleted.
        """
        