from app.domain.catalog.ports.product_repository import ProductRepository
from app.domain.catalog.product import Product


class InMemoryProductRepository(ProductRepository):
    """As for now, we use a dict to store products"""
    def __init__(
        self,
        products: list[Product] | None = None,
    ) -> None:
        initial_products = products or []

        self._products = {product.product_id: product for product in initial_products}

    async def list_all(self) -> list[Product]:
        return list(self._products.values())

    async def find_by_ids(
        self,
        product_ids: list[str],
    ) -> list[Product]:
        return [
            self._products[product_id]
            for product_id in product_ids
            if product_id in self._products
        ]
    