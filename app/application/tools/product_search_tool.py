import json
from typing import Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from app.application.usecases.catalog_search import (
    CatalogSearchUseCase,
)
from app.domain.catalog.product_search_spec import (
    ProductSearchSpec,
)


def build_product_search_tool(
    usecase: CatalogSearchUseCase,
):
    async def product_search_tool(
        normalized_query: str,
        category: Optional[str] = None,
        ship_to: Optional[str] = None,
        top_k: int = 5,
        price_max_major: Optional[float] = None,
        target_currency: str = "CNY",
    ) -> ToolChunk:
        """Search the cross-border product catalog and return product cards.

        Use this tool when the user asks to find, compare, recommend,
        or purchase products. Prices, stock, shipping availability,
        and product IDs in the answer must come from this tool.

        Args:
            normalized_query (`str`):
                Search keywords containing the product type and
                important attributes, such as "旅行装备 轻便 耐用".
            category (`str | None`):
                Optional product category, such as "旅行装备".
            ship_to (`str | None`):
                Optional two-letter destination country code,
                such as "CN" or "US".
            top_k (`int`):
                Maximum number of accepted products to return.
            price_max_major (`float | None`):
                Optional maximum price in major currency units.
            target_currency (`str`):
                Three-letter target currency code, such as "CNY".
        """
        try:
            spec = ProductSearchSpec(
                normalized_query=normalized_query,
                category=category,
                ship_to=ship_to,
                top_k=top_k,
                price_max_major=price_max_major,
                target_currency=target_currency,
            )

            result = await usecase.execute(spec)  # Execute search in usecase instead of here

        except ValueError as error:
            return ToolChunk(
                content=[
                    TextBlock(
                        type="text",
                        text=f"[error] {error}",
                    ),
                ],
                state=ToolResultState.ERROR,
            )

        return ToolChunk(
            content=[
                TextBlock(
                    type="text",
                    text=json.dumps(
                        result,
                        ensure_ascii=False,
                    ),
                ),
            ],
            state=ToolResultState.SUCCESS,
        )

    return product_search_tool