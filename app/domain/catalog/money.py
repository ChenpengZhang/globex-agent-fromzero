from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class Money:
    amount_minor: int # Note we use cents to eliminate rounding errors
    currency: str

    def __post_init__(self) -> None:
        if self.amount_minor < 0:
            raise ValueError("金额不能小于0")

        normalized_currency = self.currency.upper()
        if len(normalized_currency) != 3:
            raise ValueError("货币代码长度必须为3")

        object.__setattr__(self, "currency", normalized_currency) 
        # We have to use object.__setattr__ to bypass the frozen dataclass

    @classmethod
    def from_major_units(cls, amount: int | float | str | Decimal, currency: str) -> "Money":
        """From decimal amount to minor units (which is cents)"""
        decimal_amount = Decimal(str(amount))
        amount_minor = int(
            (decimal_amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        return cls(amount_minor=amount_minor, currency=currency)

    def to_major_units(self) -> Decimal:
        """From minor units (which is cents) to decimal amount"""
        return Decimal(self.amount_minor) / Decimal("100")
