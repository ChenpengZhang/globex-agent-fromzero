from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel

from app.infrastructure.settings import Settings


def create_chat_model(settings: Settings) -> OpenAIChatModel:
    credential = OpenAICredential(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url
    )
    return OpenAIChatModel(model=settings.llm_model, credential=credential, stream=False)
                                  