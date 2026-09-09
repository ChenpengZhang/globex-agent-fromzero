from agentscope.agent import Agent, ReActConfig
from agentscope.model import ChatModelBase
from agentscope.tool import FunctionTool, Toolkit
from agentscope.rag import KnowledgeBase

from app.application.tools.category_insight_tool import (
    build_category_insight_tool,
)
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
        knowledge_base: KnowledgeBase,
    ) -> None:
        self._model = model
        self._catalog_search = catalog_search
        self._knowledge_base = knowledge_base

    def build_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(
                build_product_search_tool(
                    self._catalog_search,
                ),
                is_read_only=True,
            ),
            FunctionTool(
                build_category_insight_tool(
                    self._knowledge_base,
                ),
                is_read_only=True,
            ),
        ]

    def build(self) -> Agent:
        return Agent(
            name="catalog_search_agent",
            system_prompt=(
                "你是 Globex 商品检索与品类知识专家。"
                "\n"
                "你只处理商品搜索、筛选、比较、推荐"
                "以及品类选购知识。"
                "\n\n"
                "【品类知识】\n"
                "当任务询问怎么挑、关键属性、参考价格区间"
                "或常见避坑点时，调用 category_insight_tool。"
                "\n"
                "知识工具只提供判断口径，"
                "不代表某件商品真实存在或可以购买。"
                "\n\n"
                "【具体商品】\n"
                "当任务要求查找、推荐、比较或购买具体商品时，"
                "必须调用 product_search_tool 获取商品事实。"
                "\n"
                "如果任务同时需要选购知识和具体商品，"
                "先调用 category_insight_tool，"
                "再调用 product_search_tool。"
                "\n"
                "不得编造商品、SKU、价格、库存或配送范围。"
                "\n\n"
                "【上下文边界】\n"
                "输入任务必须是自包含的；"
                "你看不到 MainAgent 的其他对话历史。"
                "\n"
                "完成任务后，只返回简洁、可验证的结论。"
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
    