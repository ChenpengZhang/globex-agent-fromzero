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

    redis_url: str
    queue_enabled: bool
    worker_concurrency: int
    queue_max_deliveries: int
    queue_priority_enabled: bool
    queue_large_request_turns: int
    semantic_cache_enabled: bool
    semantic_cache_threshold: float

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

    redis_url = os.getenv(
        "REDIS_URL",
        "",
    ).strip()

    queue_enabled = _read_bool(
        "QUEUE_ENABLED",
        False,
    )

    worker_concurrency = int(
        os.getenv(
            "WORKER_CONCURRENCY",
            "1",
        )
    )

    if worker_concurrency < 1:
        raise RuntimeError(
            "WORKER_CONCURRENCY must be at least one"
        )

    queue_max_deliveries = int(
        os.getenv(
            "QUEUE_MAX_DELIVERIES",
            "3",
        )
    )

    if queue_max_deliveries < 1:
        raise RuntimeError(
            "QUEUE_MAX_DELIVERIES must be at least one"
        )

    queue_priority_enabled = _read_bool(
        "QUEUE_PRIORITY_ENABLED",
        True,
    )

    queue_large_request_turns = int(
        os.getenv(
            "QUEUE_LARGE_REQUEST_TURNS",
            "30",
        )
    )

    if queue_large_request_turns < 1:
        raise RuntimeError(
            "QUEUE_LARGE_REQUEST_TURNS must be at least one"
        )

    if queue_enabled and not redis_url:
        raise RuntimeError(
            "QUEUE_ENABLED requires REDIS_URL"
        )

    semantic_cache_enabled = _read_bool(
        "SEMANTIC_CACHE_ENABLED",
        True,
    )

    semantic_cache_threshold = float(
        os.getenv(
            "SEMANTIC_CACHE_THRESHOLD",
            "0.95",
        )
    )

    if not 0 < semantic_cache_threshold <= 1:
        raise RuntimeError(
            "SEMANTIC_CACHE_THRESHOLD must be "
            "greater than zero and at most one"
        )

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
        redis_url=redis_url,
        queue_enabled=queue_enabled,
        worker_concurrency=worker_concurrency,
        queue_max_deliveries=queue_max_deliveries,
        queue_priority_enabled=queue_priority_enabled,
        queue_large_request_turns=queue_large_request_turns,
        semantic_cache_enabled=(
            semantic_cache_enabled
        ),
        semantic_cache_threshold=(
            semantic_cache_threshold
        ),
        preference_relevance_enabled=(
            preference_relevance_enabled
        ),
        preference_top_k=preference_top_k,
        preference_subagent_inject=(
            preference_subagent_inject
        ),
    )
