from abc import ABC, abstractmethod

from app.domain.catalog.product import Product


class ProductRepository(ABC):
    @abstractmethod
    async def list_all(self) -> list[Product]:
        """returns all products."""

    @abstractmethod
    async def find_by_ids(
        self,
        product_ids: list[str],
    ) -> list[Product]:
        """returns listed products by ids."""

    @abstractmethod
    async def find_by_id(
        self,
        product_id: str,
    ) -> Product | None:
        """Return one product by ID."""