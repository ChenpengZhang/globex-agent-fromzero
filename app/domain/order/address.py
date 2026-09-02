from dataclasses import dataclass


@dataclass(frozen=True)
class Address:
    recipient_name: str
    country: str
    state: str
    city: str
    address_line: str
    postal_code: str
    phone: str

    def __post_init__(self) -> None:
        required_fields = (
            "recipient_name",
            "country",
            "city",
            "address_line",
            "postal_code",
            "phone",
        )

        for field_name in required_fields:
            normalized_value = getattr(self, field_name).strip()

            if not normalized_value:
                raise ValueError(f"地址字段不能为空: {field_name}")

            object.__setattr__(
                self,
                field_name,
                normalized_value,
            )

        normalized_state = self.state.strip()
        object.__setattr__(self, "state", normalized_state)

        normalized_country = self.country.upper()

        if len(normalized_country) != 2:
            raise ValueError("国家代码必须是两个字符")

        object.__setattr__(
            self,
            "country",
            normalized_country,
        )

    def one_line(self) -> str:
        location_parts = [
            self.country,
            self.state,
            self.city,
            self.address_line,
            self.postal_code,
        ]

        location = ", ".join(
            part for part in location_parts if part
        )

        return (
            f"{location} "
            f"({self.recipient_name}, {self.phone})"
        )
    