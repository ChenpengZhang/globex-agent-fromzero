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

        if (
            not isinstance(self.stock, int)
            or isinstance(self.stock, bool)
            or self.stock < 0
        ):
            raise ValueError("库存必须是非负整数")

    def is_available(self, quantity: int = 1) -> bool:
        return (
            self._is_positive_integer(quantity)
            and self.stock >= quantity
        )

    def deduct_stock(self, quantity: int) -> None:
        if not self._is_positive_integer(quantity):
            raise ValueError("扣减数量必须是正整数")

        if not self.is_available(quantity):
            raise ValueError(
                f"库存不足: sku_id={self.sku_id}, "
                f"requested={quantity}, "
                f"available={self.stock}"
            )

        self.stock -= quantity

    def restore_stock(self, quantity: int) -> None:
        if not self._is_positive_integer(quantity):
            raise ValueError("回补数量必须是正整数")

        self.stock += quantity

    @staticmethod
    def _is_positive_integer(quantity: object) -> bool:
        return (
            isinstance(quantity, int)
            and not isinstance(quantity, bool)
            and quantity > 0
        )
    