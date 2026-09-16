from pathlib import Path

import numpy as np

from src.embedding_cache import EmbeddingCache


def test_cache_round_trip_and_text_invalidation(tmp_path: Path) -> None:
    path = tmp_path / "vectors.sqlite3"
    expected = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)
    with EmbeddingCache(path) as cache:
        assert cache.get("model", "P1", "first text") is None
        cache.put("model", "P1", "first text", expected)
        cache.commit()
        np.testing.assert_allclose(cache.get("model", "P1", "first text"), expected)
        assert cache.get("model", "P1", "changed text") is None
