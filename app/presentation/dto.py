from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class SubmitIntentRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    shopping_session_id: str | None = Field(
        default=None,
        min_length=1,
    )
    buyer_id: str = Field(
        min_length=1,
    )
    locale: str = Field(
        default="zh-CN",
        min_length=1,
    )
    currency: str = Field(
        default="CNY",
        min_length=3,
        max_length=3,
    )
    raw_query: str = Field(
        min_length=1,
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(
        cls,
        value: str,
    ) -> str:
        return value.upper()


class SubmitIntentResponse(BaseModel):
    shopping_session_id: str
    final_text: str
    