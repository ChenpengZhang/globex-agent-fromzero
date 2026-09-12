import logging
import math
from collections.abc import Sequence

from app.domain.buyer.preference import BuyerPreference
from app.domain.catalog.ports.retrieval_ports import (
    EmbeddingClient,
)


logger = logging.getLogger(__name__)


def _cosine_similarity(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    if len(left) != len(right):
        return 0.0

    dot_product = sum(
        left_value * right_value
        for left_value, right_value in zip(
            left,
            right,
        )
    )
    left_norm = math.sqrt(
        sum(value * value for value in left)
    )
    right_norm = math.sqrt(
        sum(value * value for value in right)
    )

    if left_norm == 0 or right_norm == 0:
        return 0.0

    return dot_product / (left_norm * right_norm)


def render_preference_lines(
    preferences: Sequence[BuyerPreference],
) -> str:
    """
    Render stable preference lines shared by all Agents.

    Example: 
    - [like] 喜欢轻量化产品
    - [dislike] 不要塑料材质
    """

    return "\n".join(
        (
            f"- [{preference.kind}] "
            f"{preference.statement}"
        )
        for preference in preferences
    )


def render_preference_hint(
    preferences: Sequence[BuyerPreference],
) -> str:
    """Render a buyer-specific hint outside the system prompt."""

    return (
        "<buyer-preferences>\n"
        "以下是该买家的长期偏好，来自历史会话。"
        "推荐和检索时应参考这些信息：\n"
        "- dislike 表示必须避免的限制或黑名单；\n"
        "- like 表示用于排序的软偏好。\n"
        f"{render_preference_lines(preferences)}\n"
        "</buyer-preferences>"
    )


class PreferenceSelector:
    """Select preferences relevant to the current request."""

    def __init__(
        self,
        embedder: EmbeddingClient | None = None,
        relevance_enabled: bool = False,
    ) -> None:
        self._embedder = embedder
        self._relevance_enabled = (
            relevance_enabled
            and embedder is not None
        )

    async def select(
        self,
        preferences: Sequence[BuyerPreference],
        query: str,
        top_k: int,
    ) -> list[BuyerPreference]:
        if not preferences:
            return []

        dislikes = [
            preference
            for preference in preferences
            if preference.kind == "dislike"
        ]
        likes = [
            preference
            for preference in preferences
            if preference.kind == "like"
        ]

        if top_k <= 0:
            return dislikes

        if len(likes) <= top_k:
            selected_likes = likes
        elif (
            self._relevance_enabled
            and query.strip()
        ):
            selected_likes = (
                await self._rank_by_relevance(
                    likes=likes,
                    query=query,
                    top_k=top_k,
                )
                # if enabled then rank by relevance
            )
        else:
            selected_likes = self._latest_first(
                likes,
                top_k,
            )
            # else rank by latest

        return dislikes + selected_likes

    async def _rank_by_relevance(
        self,
        likes: list[BuyerPreference],
        query: str,
        top_k: int,
    ) -> list[BuyerPreference]:
        embedder = self._embedder

        if embedder is None:
            return self._latest_first(
                likes,
                top_k,
            )

        try:
            preference_vectors = (
                await embedder.embed_batch(
                    [
                        preference.statement
                        for preference in likes
                    ]
                )
            )
            query_vector = await embedder.embed(query)
        except Exception as error:
            logger.warning(
                "Preference relevance ranking failed; "
                "falling back to recency: %s",
                error,
            )
            return self._latest_first(
                likes,
                top_k,
            )

        invalid_vectors = (
            len(preference_vectors) != len(likes)
            or not query_vector
            or any(
                len(vector) != len(query_vector)
                for vector in preference_vectors
            )
        )

        if invalid_vectors:
            logger.warning(
                "Preference embeddings were invalid; "
                "falling back to recency",
            )
            return self._latest_first(
                likes,
                top_k,
            )

        scored = [
            (
                _cosine_similarity(
                    vector,
                    query_vector,
                ),
                index,
                preference,
            )
            for index, (vector, preference) in enumerate(
                zip(preference_vectors, likes)
            )
        ]

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1],
            )
        )

        selected = {
            preference
            for _, _, preference in scored[:top_k]
        }

        return [
            preference
            for preference in likes
            if preference in selected
        ]

    @staticmethod
    def _latest_first(
        likes: list[BuyerPreference],
        top_k: int,
    ) -> list[BuyerPreference]:
        newest = sorted(
            likes,
            key=lambda preference: preference.created_at,
            reverse=True,
        )[:top_k]

        return [
            preference
            for preference in likes
            if preference in newest
        ]
