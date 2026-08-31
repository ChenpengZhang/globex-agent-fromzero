from agentscope.agent import Agent, ReActConfig
from agentscope.model import OpenAIChatModel
from agentscope.tool import Toolkit


def create_main_agent(model: OpenAIChatModel) -> Agent:
    """Create main agent"""
    return Agent(
        name = "commerce_concierge",
        system_prompt=(
            "你是Globex跨境电商助手。请使用简洁，准确的中文回答用户。"
            "当前版本没有商品数据库和业务工具。因此不得编造商品、价格、库存或订单信息。"
        ),
        model = model,
        toolkit = Toolkit(tools = []),
        react_config = ReActConfig(max_iters = 3),
    )
