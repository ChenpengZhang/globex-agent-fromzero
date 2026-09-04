from agentscope.agent import Agent, ReActConfig
from agentscope.model import ChatModelBase
from agentscope.tool import FunctionTool, Toolkit

from app.application.tools.product_search_tool import (
    build_product_search_tool,
)
from app.application.usecases.catalog_search import (
    CatalogSearchUseCase,
)


class SearchAgentFactory:
    def __init__(
        self,
        model: ChatModelBase,
        catalog_search: CatalogSearchUseCase,
    ) -> None:
        self._model = model
        self._catalog_search = catalog_search

    def build_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(
                build_product_search_tool(
                    self._catalog_search,
                ),
                is_read_only=True,
            )
        ]

    def build(self) -> Agent:
        return Agent(
            name="catalog_search_agent",
            system_prompt=(
                "你是 Globex 商品检索专家。"
                "\n"
                "你只处理商品搜索、筛选、比较和推荐任务。"
                "\n"
                "必须调用 product_search_tool 获取商品事实，"
                "不得编造商品、SKU、价格、库存或配送范围。"
                "\n"
                "输入任务必须是自包含的；"
                "你看不到 MainAgent 的其他对话历史。"
                "\n"
                "完成任务后，只返回简洁、可验证的检索结论。"
                "\n"
                "如果工具返回 [error]，"
                "必须如实返回错误，不得猜测结果。"
            ),
            model=self._model,
            toolkit=Toolkit(
                tools=self.build_tools(),
            ),
            react_config=ReActConfig(
                max_iters=5,
            ),
        )
    