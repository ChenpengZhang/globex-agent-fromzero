from agentscope.agent import Agent, ReActConfig
from agentscope.model import ChatModelBase
from agentscope.tool import FunctionTool, Toolkit


def create_main_agent(
    model: ChatModelBase,
    tools: list[FunctionTool],
) -> Agent:
    """Create the Globex main commerce agent."""

    return Agent(
        name="commerce_concierge",
        system_prompt=(
            "你是 Globex 跨境电商助手。"
            "请使用简洁、准确的中文回答用户。"
            "\n\n"
            "当用户要求查找、推荐、比较或购买商品时，"
            "必须先调用 product_search_tool，不能依靠记忆编造商品。"
            "\n"
            "调用工具前，从用户需求中提取："
            "标准化检索词、品类、收货国家、预算上限和目标币种。"
            "\n"
            "商品 ID、SKU ID、价格、库存和配送范围"
            "必须来自工具返回结果。"
            "\n"
            "如果工具返回 filtered_out，"
            "应说明商品是因为超预算、无法配送或币种不支持而被过滤，"
            "不能把它描述成商品不存在。"
            "\n"
            "如果工具返回 [error]，应如实告知用户，"
            "不得编造结果填补错误。"
        ),
        model=model,
        toolkit=Toolkit(
            tools=tools,
        ),
        react_config=ReActConfig(
            max_iters=5,
        ),
    )


class MainAgentFactory:
    def __init__(
        self,
        model: ChatModelBase,
        tools: list[FunctionTool],
    ) -> None:
        self._model = model
        self._tools = list(tools)

    def build(self) -> Agent:
        return create_main_agent(
            model=self._model,
            tools=list(self._tools),
        )
    