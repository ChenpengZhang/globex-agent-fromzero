from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.catalog.product import Product


class EmbeddingClient(ABC):
    @abstractmethod
    async def embed(
        self,
        text: str,
    ) -> list[float]:
        """Convert one text into an embedding vector."""

    @abstractmethod
    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Convert texts into vectors in the same order."""


@dataclass(frozen=True)
class VectorHit:
    product_id: str
    score: float


class ProductVectorIndex(ABC):
    @abstractmethod
    async def ensure_ready(
        self,
        vector_dim: int,
    ) -> None:
        """Idempotently create the product collection."""

    @abstractmethod
    async def upsert_products(
        self,
        products: list[Product],
        embeddings: list[list[float]],
    ) -> None:
        """Insert or replace product vectors."""

    @abstractmethod
    async def search(
        self,
        embedding: list[float],
        top_n: int,
    ) -> list[VectorHit]:
        """Return product IDs ordered by vector relevance."""


class Reranker(ABC):
    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        """Return one relevance score per document."""
