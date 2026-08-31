from dataclasses import dataclass

from app.domain.catalog.money import Money


@dataclass
class Sku:
    sku_id: str
    spec: str
    price: Money
    stock: int

    def __post_init__(self) -> None:
        if not self.sku_id:
            raise ValueError("sku_id 不能为空")

        if self.stock < 0:
            raise ValueError("库存不能小于零")

    def is_available(self, quantity: int = 1) -> bool:
        return quantity > 0 and self.stock >= quantity
    