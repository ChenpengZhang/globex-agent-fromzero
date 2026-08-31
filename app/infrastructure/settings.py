import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str


def load_settings() -> Settings:
    load_dotenv()

    base_url = os.getenv("LLM_BASE_URL", "")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")

    missing = [ 
        name for name, value in {
            "LLM_BASE_URL": base_url,
            "LLM_API_KEY": api_key,
            "LLM_MODEL": model
        }.items() if not value
    ]

    if missing:
        raise RuntimeError(f"Missing required environment variables: {missing}")

    return Settings(
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_model=model,
    )
