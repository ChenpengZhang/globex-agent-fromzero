import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from app.domain.catalog.ports.retrieval_ports import (
    EmbeddingClient,
)
from app.infrastructure.cache.redis_cache import RedisCache


logger = logging.getLogger(__name__)

_SEMANTIC_CACHE_TTL_SECONDS = 24 * 60 * 60
_BUCKET_LIMIT = 30

_UNSAFE_QUERY_PATTERN = re.compile(
    "|".join(
        [
            r"下单",
            r"购买",
            r"付款",
            r"支付",
            r"取消",
            r"退单",
            r"退款",
            r"修改地址",
            r"改地址",
            r"订单号",
            r"我的订单",
            r"GBX-",
            r"刚才",
            r"刚刚",
            r"上面",
            r"前面",
            r"那个",
            r"这个",
            r"它",
            r"买",
            r"记住",
            r"忘记",
            r"撤回",
            r"长期偏好",
            r"我喜欢",
            r"我不喜欢",
            r"\b(?:remember|forget|preference)\b",
            r"\bI (?:like|dislike|prefer|avoid)\b",
            r"\b(?:buy|purchase|checkout|pay|cancel|refund)\b",
            r"\b(?:order|previous|above|that one)\b",
        ]
    ),
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticHit:
    reply: str
    similarity: float
    matched_query: str


def _normalize_query(
    query: str,
) -> str:
    collapsed = re.sub(
        r"\s+",
        " ",
        query.strip(),
    )

    return collapsed.rstrip(
        "？?。.!！~"
    )


def _parse_vector(
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


def _cosine_similarity(
    left: list[float],
    right: list[float],
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

    return dot_product / (
        left_norm * right_norm
    )


def is_cacheable_query(
    query: str,
) -> bool:
    normalized = _normalize_query(query)

    if not normalized:
        return False

    return _UNSAFE_QUERY_PATTERN.search(
        normalized
    ) is None


class SemanticCache:
    """
    Reuse final replies for sufficiently similar safe read queries.

    Entries are isolated by buyer, prompt/model namespace, and
    buyer-specific state such as the preference fingerprint.
    """

    def __init__(
        self,
        cache: RedisCache,
        embedder: EmbeddingClient,
        threshold: float = 0.95,
        enabled: bool = True,
        namespace: str = "",
    ) -> None:
        self._cache = cache
        self._embedder = embedder
        self._threshold = threshold
        self._enabled = (
            enabled
            and cache.enabled
        )
        self._namespace = namespace

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _bucket_key(
        self,
        buyer_id: str,
        scope: str = "",
    ) -> str:
        digest = hashlib.sha256(
            (
                f"{self._namespace}\n"
                f"{buyer_id}\n"
                f"{scope}"
            ).encode("utf-8")
        ).hexdigest()[:24]

        return f"globex:semantic:{digest}"

    async def _load_entries(
        self,
        buyer_id: str,
        scope: str,
    ) -> list[dict[str, Any]]:
        try:
            value = await self._cache.get_json(
                self._bucket_key(
                    buyer_id,
                    scope,
                )
            )
        except Exception as error:
            logger.warning(
                "Semantic cache read failed; "
                "using an empty bucket: %s",
                error,
            )
            return []

        if not isinstance(value, list):
            return []

        return [
            entry
            for entry in value
            if isinstance(entry, dict)
        ]

    async def lookup(
        self,
        buyer_id: str,
        query: str,
        has_history: bool,
        scope: str = "",
    ) -> SemanticHit | None:
        if (
            not self._enabled
            or has_history
            or not is_cacheable_query(query)
        ):
            return None

        entries = await self._load_entries(
            buyer_id,
            scope,
        )

        if not entries:
            return None

        try:
            query_vector = await self._embedder.embed(
                _normalize_query(query)
            )
        except Exception as error:
            logger.warning(
                "Semantic cache query embedding failed; "
                "treating it as a miss: %s",
                error,
            )
            return None

        best_hit: SemanticHit | None = None

        for entry in entries:
            candidate_vector = _parse_vector(
                entry.get("vector")
            )
            reply = entry.get("reply")
            matched_query = entry.get("query")

            if (
                candidate_vector is None
                or not isinstance(reply, str)
                or not reply
                or not isinstance(matched_query, str)
            ):
                continue

            similarity = _cosine_similarity(
                query_vector,
                candidate_vector,
            )

            if similarity < self._threshold:
                continue

            if (
                best_hit is None
                or similarity > best_hit.similarity
            ):
                best_hit = SemanticHit(
                    reply=reply,
                    similarity=round(
                        similarity,
                        4,
                    ),
                    matched_query=matched_query,
                )

        return best_hit

    async def remember(
        self,
        buyer_id: str,
        query: str,
        reply: str,
        has_history: bool,
        scope: str = "",
    ) -> None:
        if (
            not self._enabled
            or has_history
            or not is_cacheable_query(query)
            or not reply
            or reply.startswith("[error]")
        ):
            return

        normalized_query = _normalize_query(
            query
        )

        try:
            vector = await self._embedder.embed(
                normalized_query
            )
        except Exception as error:
            logger.warning(
                "Semantic cache reply embedding failed; "
                "skipping cache update: %s",
                error,
            )
            return

        key = self._bucket_key(
            buyer_id,
            scope,
        )
        entries = await self._load_entries(
            buyer_id,
            scope,
        )

        entries = [
            entry
            for entry in entries
            if entry.get("query")
            != normalized_query
        ]
        entries.append(
            {
                "query": normalized_query,
                "reply": reply,
                "vector": vector,
            }
        )

        try:
            await self._cache.set_json(
                key,
                entries[-_BUCKET_LIMIT:],
                _SEMANTIC_CACHE_TTL_SECONDS,
            )
        except Exception as error:
            logger.warning(
                "Semantic cache write failed; "
                "skipping cache update: %s",
                error,
            )
