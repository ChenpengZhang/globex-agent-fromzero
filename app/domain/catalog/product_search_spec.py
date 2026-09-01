from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class ProductSearchSpec:
    normalized_query: str
    category: str | None = None
    ship_to: str | None = None
    top_k: int = 5
    price_max_major: Decimal | int | float | str | None = None
    target_currency: str = "CNY"

    def __post_init__(self) -> None:
        normalized_query = self.normalized_query.strip()
        if not normalized_query:
            raise ValueError("normalized_query 不能为空")

        object.__setattr__(self, "normalized_query", normalized_query)

        if self.category is not None:
            normalized_category = self.category.strip()
            object.__setattr__(self, "category", normalized_category or None)

        if self.ship_to is not None:
            normalized_ship_to = self.ship_to.strip().upper()

            if len(normalized_ship_to) != 2:
                raise ValueError("ship_to 必须是二位国家代码，例如 CN、US")

            object.__setattr__(self, "ship_to", normalized_ship_to)

        if self.top_k < 1 or self.top_k > 20:
            raise ValueError("top_k 必须在 1 到 20 之间")

        normalized_currency = self.target_currency.strip().upper()
        if len(normalized_currency) != 3:
            raise ValueError("target_currency 必须是三位币种代码")

        object.__setattr__(self, "target_currency", normalized_currency)

        if self.price_max_major is not None:
            try:
                normalized_price = Decimal(str(self.price_max_major))
            except InvalidOperation as error:
                raise ValueError( "price_max_major 必须是有效数字") from error

            if normalized_price < 0:
                raise ValueError("price_max_major 不能小于零")

            object.__setattr__(self, "price_max_major", normalized_price)