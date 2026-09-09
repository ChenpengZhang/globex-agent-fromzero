import httpx

from app.domain.catalog.ports.retrieval_ports import (
    Reranker,
)
from app.infrastructure.settings import Settings


class HttpReranker(Reranker):
    def __init__(
        self,
        settings: Settings,
        timeout_seconds: float = 3.0,
    ) -> None:
        self._base_url = (
            settings.reranker_base_url.rstrip("/")
        )
        self._model = settings.reranker_model
        self._timeout_seconds = timeout_seconds

    async def rerank(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        if not documents:
            return []

        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
        ) as client:
            response = await client.post(
                f"{self._base_url}/rerank",
                json={
                    "model": self._model,
                    "query": query,
                    "documents": documents,
                },
            )

            response.raise_for_status()
            body = response.json()

        results = body.get("results")

        if (
            not isinstance(results, list)
            or len(results) != len(documents)
        ):
            raise RuntimeError(
                f"rerank 响应格式错误：{body}"
            )

        scores = [0.0] * len(documents)
        seen_indices: set[int] = set()

        for item in results:
            index = item.get("index")

            if (
                not isinstance(index, int)
                or index < 0
                or index >= len(documents)
                or index in seen_indices
            ):
                raise RuntimeError(
                    f"rerank 响应 index 错误：{body}"
                )

            seen_indices.add(index)

            raw_score = item.get(
                "relevance_score",
                item.get("score"),
            )

            if not isinstance(raw_score, int | float):
                raise RuntimeError(
                    f"rerank 响应 score 错误：{body}"
                )

            scores[index] = float(raw_score)

        return scores
    