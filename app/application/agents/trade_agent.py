from agentscope.agent import Agent, ReActConfig
from agentscope.model import ChatModelBase
from agentscope.tool import FunctionTool, Toolkit

from app.application.agents.permissions import (
    allow_business_tools,
)
from app.application.tools.order_tools import (
    build_cancel_order_tool,
    build_place_order_tool,
    build_query_order_tool,
)
from app.application.usecases.cancel_order import (
    CancelOrderUseCase,
)
from app.application.usecases.place_order import (
    PlaceOrderUseCase,
)
from app.application.usecases.query_order import (
    QueryOrderUseCase,
)


class TradeAgentFactory:
    def __init__(
        self,
        model: ChatModelBase,
        place_order: PlaceOrderUseCase,
        query_order: QueryOrderUseCase,
        cancel_order: CancelOrderUseCase,
    ) -> None:
        self._model = model
        self._place_order = place_order
        self._query_order = query_order
        self._cancel_order = cancel_order

    def build_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(
                build_place_order_tool(
                    self._place_order,
                ),
                is_read_only=False,
            ),
            FunctionTool(
                build_query_order_tool(
                    self._query_order,
                ),
                is_read_only=True,
            ),
            FunctionTool(
                build_cancel_order_tool(
                    self._cancel_order,
                ),
                is_read_only=False,
            ),
        ]

    def build(self) -> Agent:
        agent = Agent(
            name="order_trade_agent",
            system_prompt=(
                "你是 Globex 订单交易专家。"
                "\n"
                "你只处理创建订单、查询订单和取消订单。"
                "\n"
                "商品、SKU、数量和地址必须来自"
                "传入的自包含任务，不得猜测缺失参数。"
                "\n"
                "只有任务明确说明用户已经确认下单时，"
                "才能调用 place_order_tool。"
                "\n"
                "查询订单调用 query_order_tool。"
                "\n"
                "取消订单必须有订单号和取消原因，"
                "并调用 cancel_order_tool。"
                "\n"
                "buyer 身份由 ShoppingContext 自动注入，"
                "不得自行生成或修改。"
                "\n"
                "只有工具返回成功后才能声称交易成功；"
                "工具返回 [error] 时必须如实报告。"
            ),
            model=self._model,
            toolkit=Toolkit(
                tools=self.build_tools(),
            ),
            react_config=ReActConfig(
                max_iters=5,
            ),
        )

        return allow_business_tools(agent)
    