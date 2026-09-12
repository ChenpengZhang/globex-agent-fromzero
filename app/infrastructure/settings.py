import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str

    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_dim: int

    reranker_base_url: str
    reranker_model: str

    qdrant_url: str
    category_kb_collection: str
    product_vector_collection: str

    data_dir: Path
    database_url: str

    preference_relevance_enabled: bool
    preference_top_k: int
    preference_subagent_inject: bool


def _read_bool(
    name: str,
    default: bool,
) -> bool:
    default_value = "1" if default else "0"
    raw_value = os.getenv(
        name,
        default_value,
    ).strip().lower()

    if raw_value in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if raw_value in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    raise RuntimeError(
        f"{name} must be a boolean value"
    )

def load_settings() -> Settings:
    load_dotenv()

    llm_base_url = os.getenv(
        "LLM_BASE_URL",
        "",
    ).strip()
    llm_api_key = os.getenv(
        "LLM_API_KEY",
        "",
    ).strip()
    llm_model = os.getenv(
        "LLM_MODEL",
        "",
    ).strip()

    missing = [
        name
        for name, value in {
            "LLM_BASE_URL": llm_base_url,
            "LLM_API_KEY": llm_api_key,
            "LLM_MODEL": llm_model,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            f"{missing}"
        )

    embedding_base_url = (
        os.getenv("EMBEDDING_BASE_URL", "").strip()
        or llm_base_url
    )
    embedding_api_key = (
        os.getenv("EMBEDDING_API_KEY", "").strip()
        or llm_api_key
    )
    embedding_model = (
        os.getenv(
            "EMBEDDING_MODEL",
            "text-embedding-v4",
        ).strip()
    )
    embedding_dim = int(
        os.getenv("EMBEDDING_DIM", "1024")
    )

    if embedding_dim <= 0:
        raise RuntimeError(
            "EMBEDDING_DIM 必须是正整数"
        )

    raw_data_dir = os.getenv(
        "DATA_DIR",
        ".data",
    ).strip()
    data_dir = Path(raw_data_dir)

    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / raw_data_dir

    database_url = os.getenv(
        "DATABASE_URL",
        "",
    ).strip()

    if not database_url:
        database_url = (
            f"sqlite+aiosqlite:///"
            f"{data_dir / 'globex.db'}"
        )

    preference_top_k = int(
        os.getenv(
            "PREFERENCE_TOP_K",
            "5",
        )
    )

    if preference_top_k < 0:
        raise RuntimeError(
            "PREFERENCE_TOP_K must be greater than or equal to zero"
        )

    preference_relevance_enabled = _read_bool(
        "PREFERENCE_RELEVANCE_ENABLED",
        False,
    )

    preference_subagent_inject = _read_bool(
        "PREFERENCE_SUBAGENT_INJECT",
        True,
    )

    return Settings(
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        embedding_base_url=embedding_base_url,
        embedding_api_key=embedding_api_key,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        qdrant_url=os.getenv(
            "QDRANT_URL",
            "",
        ).strip(),
        category_kb_collection=os.getenv(
            "CATEGORY_KB_COLLECTION",
            "globex_category_kb",
        ).strip(),
        product_vector_collection=os.getenv(
            "PRODUCT_VECTOR_COLLECTION",
            "globex_product_vectors",
        ).strip(),
        reranker_base_url=os.getenv(
            "RERANKER_BASE_URL",
            "",
        ).strip(),
        reranker_model=os.getenv(
            "RERANKER_MODEL",
            "",
        ).strip(),
        data_dir=data_dir,
        database_url=database_url,
                preference_relevance_enabled=(
            preference_relevance_enabled
        ),
        preference_top_k=preference_top_k,
        preference_subagent_inject=(
            preference_subagent_inject
        ),
    )
