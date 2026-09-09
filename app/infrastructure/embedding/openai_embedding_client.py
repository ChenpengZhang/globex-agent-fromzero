import httpx

from app.domain.catalog.ports.retrieval_ports import (
    EmbeddingClient,
)
from app.infrastructure.settings import Settings


_MAX_BATCH_SIZE = 10


class OpenAIEmbeddingClient(EmbeddingClient):
    def __init__(
        self,
        settings: Settings,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = (
            settings.embedding_base_url.rstrip("/")
        )
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model
        self._timeout_seconds = timeout_seconds

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

        vectors: list[list[float]] = []

        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
        ) as client:
            for start in range(
                0,
                len(texts),
                _MAX_BATCH_SIZE,
            ):
                batch = texts[
                    start : start + _MAX_BATCH_SIZE
                ]
                batch_vectors = await self._embed_batch(
                    client=client,
                    texts=batch,
                )
                vectors.extend(batch_vectors)

        return vectors

    async def _embed_batch(
        self,
        client: httpx.AsyncClient,
        texts: list[str],
    ) -> list[list[float]]:
        response = await client.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": (
                    f"Bearer {self._api_key}"
                ),
            },
            json={
                "model": self._model,
                "input": texts,
            },
        )
        response.raise_for_status()

        if not response.content:
            raise RuntimeError(
                "embedding 服务返回了空响应"
            )

        body = response.json()
        data = body.get("data")

        if not isinstance(data, list):
            raise RuntimeError(
                f"embedding 响应格式错误：{body}"
            )

        ordered = sorted(
            data,
            key=lambda item: item["index"],
        )

        vectors = [
            item["embedding"]
            for item in ordered
        ]

        if len(vectors) != len(texts):
            raise RuntimeError(
                "embedding 返回的向量数量与输入数量不一致"
            )

        return vectors
    