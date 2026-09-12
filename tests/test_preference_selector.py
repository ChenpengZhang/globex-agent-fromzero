import pytest

from app.application.memory.preference_selector import (
    PreferenceSelector,
    render_preference_hint,
    render_preference_lines,
)
from app.domain.buyer.preference import BuyerPreference
from app.domain.catalog.ports.retrieval_ports import EmbeddingClient


TERMS = (
    "coffee",
    "travel",
    "camping",
    "plastic",
    "design",
)


class AxisEmbeddingClient(EmbeddingClient):
    def __init__(self) -> None:
        self.embed_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    async def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return [
            1.0 if term in text else 0.0
            for term in TERMS
        ]

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        return [
            [
                1.0 if term in text else 0.0
                for term in TERMS
            ]
            for text in texts
        ]


class BrokenEmbeddingClient(EmbeddingClient):
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        raise RuntimeError("embedding unavailable")


class InvalidEmbeddingClient(EmbeddingClient):
    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        if self.mode == "count":
            return [[1.0, 0.0]]

        return [[1.0] for _ in texts]


def preference(
    kind: str,
    statement: str,
    created_at: str,
) -> BuyerPreference:
    return BuyerPreference(
        buyer_id="buyer-001",
        kind=kind,
        statement=statement,
        created_at=created_at,
    )


def statements(
    preferences: list[BuyerPreference],
) -> list[str]:
    return [item.statement for item in preferences]


def test_preference_hint_has_stable_explicit_structure() -> None:
    preferences = [
        preference("dislike", "no plastic", "2026-01-01"),
        preference("like", "minimal design", "2026-01-02"),
    ]

    lines = render_preference_lines(preferences)
    hint = render_preference_hint(preferences)

    assert lines == (
        "- [dislike] no plastic\n"
        "- [like] minimal design"
    )
    assert hint.startswith("<buyer-preferences>\n")
    assert lines in hint
    assert hint.endswith("\n</buyer-preferences>")


@pytest.mark.asyncio
async def test_dislikes_are_never_truncated_and_come_first() -> None:
    preferences = [
        preference("like", "coffee gear", "2026-01-01"),
        preference("dislike", "no plastic", "2026-01-02"),
        preference("dislike", "no leather", "2026-01-03"),
        preference("dislike", "no nickel", "2026-01-04"),
        preference("like", "travel gear", "2026-01-05"),
    ]

    selected = await PreferenceSelector(
        AxisEmbeddingClient(),
        relevance_enabled=True,
    ).select(
        preferences,
        query="coffee cup",
        top_k=1,
    )

    assert [item.kind for item in selected[:3]] == [
        "dislike",
        "dislike",
        "dislike",
    ]
    assert statements(selected[:3]) == [
        "no plastic",
        "no leather",
        "no nickel",
    ]
    assert statements(selected[3:]) == ["coffee gear"]


@pytest.mark.asyncio
async def test_top_k_zero_keeps_only_dislikes() -> None:
    preferences = [
        preference("like", "minimal design", "2026-01-01"),
        preference("dislike", "no plastic", "2026-01-02"),
    ]

    selected = await PreferenceSelector().select(
        preferences,
        query="anything",
        top_k=0,
    )

    assert statements(selected) == ["no plastic"]


@pytest.mark.asyncio
async def test_likes_within_limit_skip_embedding() -> None:
    embedder = AxisEmbeddingClient()
    preferences = [
        preference("like", "coffee gear", "2026-01-01"),
        preference("like", "travel gear", "2026-01-02"),
    ]

    selected = await PreferenceSelector(
        embedder,
        relevance_enabled=True,
    ).select(
        preferences,
        query="coffee cup",
        top_k=5,
    )

    assert selected == preferences
    assert embedder.embed_calls == []
    assert embedder.batch_calls == []


@pytest.mark.asyncio
async def test_relevance_selects_likes_in_original_relative_order() -> None:
    preferences = [
        preference("like", "coffee gear", "2026-01-01"),
        preference("like", "travel gear", "2026-01-02"),
        preference("like", "camping style", "2026-01-03"),
    ]

    selected = await PreferenceSelector(
        AxisEmbeddingClient(),
        relevance_enabled=True,
    ).select(
        preferences,
        query="travel coffee",
        top_k=2,
    )

    assert statements(selected) == [
        "coffee gear",
        "travel gear",
    ]


@pytest.mark.asyncio
async def test_disabled_relevance_selects_latest_likes() -> None:
    preferences = [
        preference("like", "old", "2026-01-01"),
        preference("like", "middle", "2026-02-01"),
        preference("like", "new", "2026-03-01"),
    ]

    selected = await PreferenceSelector(
        AxisEmbeddingClient(),
        relevance_enabled=False,
    ).select(
        preferences,
        query="anything",
        top_k=2,
    )

    assert statements(selected) == ["middle", "new"]


@pytest.mark.asyncio
async def test_embedding_failure_falls_back_to_latest() -> None:
    preferences = [
        preference("like", "old", "2026-01-01"),
        preference("like", "new", "2026-02-01"),
    ]

    selected = await PreferenceSelector(
        BrokenEmbeddingClient(),
        relevance_enabled=True,
    ).select(
        preferences,
        query="anything",
        top_k=1,
    )

    assert statements(selected) == ["new"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["count", "dimension"])
async def test_invalid_embeddings_fall_back_to_latest(
    mode: str,
) -> None:
    preferences = [
        preference("like", "old", "2026-01-01"),
        preference("like", "new", "2026-02-01"),
    ]

    selected = await PreferenceSelector(
        InvalidEmbeddingClient(mode),
        relevance_enabled=True,
    ).select(
        preferences,
        query="anything",
        top_k=1,
    )

    assert statements(selected) == ["new"]


@pytest.mark.asyncio
async def test_empty_preferences_return_without_embedding() -> None:
    embedder = AxisEmbeddingClient()

    selected = await PreferenceSelector(
        embedder,
        relevance_enabled=True,
    ).select(
        [],
        query="coffee",
        top_k=5,
    )

    assert selected == []
    assert embedder.embed_calls == []
    assert embedder.batch_calls == []
