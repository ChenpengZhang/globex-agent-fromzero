import hashlib
import logging
from typing import Any

from app.domain.catalog.ports.retrieval_ports import (
    EmbeddingClient,
)
from app.infrastructure.cache.redis_cache import RedisCache


logger = logging.getLogger(__name__)

_EMBEDDING_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


def _parse_cached_vector(
    value: Any,
) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None

    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        for item in value
    ):
        return None

    return [
        float(item)
        for item in value
    ]


class CachedEmbeddingClient(EmbeddingClient):
    """
    Add Redis caching around another EmbeddingClient.

    The wrapped client remains responsible for generating vectors.
    This decorator only handles cache lookup and storage.
    """

    def __init__(
        self,
        inner: EmbeddingClient,
        cache: RedisCache,
        model: str,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._model = model
        self.hits = 0
        self.misses = 0

    def _key(
        self,
        text: str,
    ) -> str:
        digest = hashlib.sha256(
            f"{self._model}\n{text}".encode("utf-8")
        ).hexdigest()

        return (
            f"globex:embedding:"
            f"{self._model}:"
            f"{digest}"
        )

    async def _safe_get(
        self,
        key: str,
    ) -> list[float] | None:
        try:
            cached = await self._cache.get_json(key)
        except Exception as error:
            logger.warning(
                "Embedding cache read failed; "
                "treating it as a miss: %s",
                error,
            )
            return None

        return _parse_cached_vector(cached)

    async def _safe_set(
        self,
        key: str,
        vector: list[float],
    ) -> None:
        try:
            await self._cache.set_json(
                key,
                vector,
                _EMBEDDING_CACHE_TTL_SECONDS,
            )
        except Exception as error:
            logger.warning(
                "Embedding cache write failed; "
                "skipping cache update: %s",
                error,
            )

    async def embed(
        self,
        text: str,
    ) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float] | None] = [
            None
            for _ in texts
        ]
        pending: list[tuple[int, str]] = []

        for index, text in enumerate(texts):
            cached = await self._safe_get(
                self._key(text)
            )

            if cached is not None:
                self.hits += 1
                results[index] = cached
            else:
                self.misses += 1
                pending.append(
                    (index, text)
                )

        if pending:
            fresh_vectors = await self._inner.embed_batch(
                [
                    text
                    for _, text in pending
                ]
            )

            if len(fresh_vectors) != len(pending):
                raise RuntimeError(
                    "Embedding result count does not match "
                    "the cache-miss input count"
                )

            for (
                (index, text),
                vector,
            ) in zip(
                pending,
                fresh_vectors,
            ):
                results[index] = vector

                await self._safe_set(
                    self._key(text),
                    vector,
                )

        missing_indices = [
            index
            for index, vector in enumerate(results)
            if vector is None
        ]

        if missing_indices:
            raise RuntimeError(
                "Embedding results are missing at indices: "
                f"{missing_indices}"
            )

        return [
            vector
            for vector in results
            if vector is not None
        ]
