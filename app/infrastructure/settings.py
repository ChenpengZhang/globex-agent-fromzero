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
        data_dir = PROJECT_ROOT / data_dir

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
    )
