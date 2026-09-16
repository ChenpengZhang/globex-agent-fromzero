from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """Small resumable vector cache owned only by the benchmark."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                namespace TEXT NOT NULL,
                item_id TEXT NOT NULL,
                text_sha256 TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                vector BLOB NOT NULL,
                PRIMARY KEY (namespace, item_id)
            )
            """
        )
        self._connection.commit()

    def get(self, namespace: str, item_id: str, text: str) -> np.ndarray | None:
        row = self._connection.execute(
            """
            SELECT text_sha256, dimension, vector
            FROM embeddings
            WHERE namespace = ? AND item_id = ?
            """,
            (namespace, item_id),
        ).fetchone()
        if row is None or row[0] != text_digest(text):
            return None
        vector = np.frombuffer(row[2], dtype=np.float32).copy()
        if vector.size != row[1]:
            return None
        return vector

    def put(self, namespace: str, item_id: str, text: str, vector: np.ndarray) -> None:
        normalized = np.asarray(vector, dtype=np.float32)
        self._connection.execute(
            """
            INSERT INTO embeddings(namespace, item_id, text_sha256, dimension, vector)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(namespace, item_id) DO UPDATE SET
                text_sha256 = excluded.text_sha256,
                dimension = excluded.dimension,
                vector = excluded.vector
            """,
            (
                namespace,
                item_id,
                text_digest(text),
                int(normalized.size),
                normalized.tobytes(),
            ),
        )

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "EmbeddingCache":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
