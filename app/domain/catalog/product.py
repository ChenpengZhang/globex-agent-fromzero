from dataclasses import dataclass

from app.domain.catalog.sku import Sku


@dataclass
class Product:
    product_id: str
    title: str
    brand: str
    category: str
    origin_country: str
    description: str
    ships_to: list[str]
    skus: list[Sku]

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("product_id 不能为空")

        if not self.title:
            raise ValueError("商品标题不能为空")

        if not self.skus:
            raise ValueError("商品至少需要一个 SKU")

    def primary_sku(self) -> Sku:
        return self.skus[0]

    def searchable_text(self) -> str:
        sku_specs = " ".join(sku.spec for sku in self.skus)

        return " ".join(
            [
                self.title,
                self.brand,
                self.category,
                self.description,
                sku_specs,
            ],
        )
    