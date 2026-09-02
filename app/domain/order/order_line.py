from dataclasses import dataclass

from app.domain.catalog.money import Money


@dataclass(frozen=True)
class OrderLine:
    product_id: str
    sku_id: str
    title: str
    unit_price: Money
    quantity: int

    def __post_init__(self) -> None:
        required_fields = (
            "product_id",
            "sku_id",
            "title",
        )

        for field_name in required_fields:
            normalized_value = getattr(self, field_name).strip()

            if not normalized_value:
                raise ValueError(
                    f"订单行字段不能为空: {field_name}"
                )

            object.__setattr__(
                self,
                field_name,
                normalized_value,
            )

        if (
            not isinstance(self.quantity, int)
            or isinstance(self.quantity, bool)
            or self.quantity <= 0
        ):
            raise ValueError("商品数量必须是正整数")

    def subtotal(self) -> Money:
        return self.unit_price.multiply(self.quantity)
    