from dataclasses import dataclass

from agentscope.agent import Agent

from app.application.agents.main_agent import create_main_agent
from app.infrastructure.llm import create_chat_model
from app.infrastructure.settings import load_settings


@dataclass
class Container:
    main_agent: Agent


def build_container() -> Container:
    settings = load_settings()
    model = create_chat_model(settings)
    main_agent = create_main_agent(model)
    return Container(
        main_agent = main_agent,
    )
