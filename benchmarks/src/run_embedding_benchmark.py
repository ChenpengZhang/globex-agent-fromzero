from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np
import pyarrow.parquet as pq
from dotenv import load_dotenv
from sklearn.feature_extraction.text import TfidfVectorizer

from src.embedding_cache import EmbeddingCache
from src.metrics import hit_rate_at_k, paired_estimate, recall_at_k


SEED = 20260912


@dataclass
class EmbeddingRunStats:
    cache_hits: int = 0
    cache_misses: int = 0
    api_requests: int = 0
    api_input_tokens: int = 0


class OpenAICompatibleEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, expected_dim: int) -> None:
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._api_key = api_key
        self._model = model
        self._expected_dim = expected_dim

    async def embed_batch(
        self,
        client: httpx.AsyncClient,
        texts: list[str],
        stats: EmbeddingRunStats,
    ) -> list[np.ndarray]:
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                response = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": texts},
                )
                stats.api_requests += 1
                if response.status_code == 429 or response.status_code >= 500:
                    raise RuntimeError(f"retryable embedding HTTP {response.status_code}")
                response.raise_for_status()
                body = response.json()
                data = sorted(body.get("data", []), key=lambda item: item["index"])
                vectors = [np.asarray(item["embedding"], dtype=np.float32) for item in data]
                if len(vectors) != len(texts):
                    raise RuntimeError("embedding response count does not match request")
                if any(vector.size != self._expected_dim for vector in vectors):
                    dimensions = sorted({int(vector.size) for vector in vectors})
                    raise RuntimeError(
                        f"embedding dimensions {dimensions} do not match configured {self._expected_dim}"
                    )
                usage = body.get("usage") or {}
                stats.api_input_tokens += int(
                    usage.get("prompt_tokens", usage.get("total_tokens", 0)) or 0
                )
                return vectors
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                detail = error.response.text.strip().replace("\n", " ")[:500]
                entitlement_sync = (
                    status == 403 and "AccessDenied.Unpurchased" in detail
                )
                if status != 429 and status < 500 and not entitlement_sync:
                    raise RuntimeError(
                        f"non-retryable embedding HTTP {status}: {detail}"
                    ) from error
                last_error = RuntimeError(f"embedding HTTP {status}: {detail}")
                if attempt == 5:
                    break
                await asyncio.sleep(min(2**attempt, 8))
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as error:
                last_error = error
                if attempt == 5:
                    break
                await asyncio.sleep(min(2**attempt, 8))
        raise RuntimeError(f"embedding batch failed after retries: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real-embedding Top-K recall benchmark")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed_pilot_5k"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache/embeddings.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/embedding_pilot_5k"))
    parser.add_argument("--env-file", type=Path, default=Path("../.env"))
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    return parser.parse_args()


def _top_ids(scores: np.ndarray, product_ids: np.ndarray, k: int) -> list[str]:
    k = min(k, scores.size)
    candidates = np.argpartition(scores, scores.size - k)[-k:]
    order = np.lexsort((product_ids[candidates], -scores[candidates]))
    return product_ids[candidates[order]].tolist()


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise RuntimeError("embedding API returned a zero vector")
    return matrix / norms


async def _embed_records(
    records: list[tuple[str, str]],
    *,
    namespace: str,
    cache: EmbeddingCache,
    embedder: OpenAICompatibleEmbedder,
    expected_dim: int,
    batch_size: int,
    concurrency: int,
    stats: EmbeddingRunStats,
) -> np.ndarray:
    vectors: list[np.ndarray | None] = []
    missing: list[tuple[int, str, str]] = []
    for index, (item_id, text) in enumerate(records):
        cached = cache.get(namespace, item_id, text)
        vectors.append(cached)
        if cached is None:
            stats.cache_misses += 1
            missing.append((index, item_id, text))
        else:
            stats.cache_hits += 1

    timeout = httpx.Timeout(60.0, connect=20.0)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        wave_size = batch_size * concurrency
        for wave_start in range(0, len(missing), wave_size):
            wave = missing[wave_start : wave_start + wave_size]
            batches = [wave[i : i + batch_size] for i in range(0, len(wave), batch_size)]
            results = await asyncio.gather(
                *[
                    embedder.embed_batch(client, [item[2] for item in batch], stats)
                    for batch in batches
                ],
                return_exceptions=True,
            )
            first_error: BaseException | None = None
            for batch, result in zip(batches, results):
                if isinstance(result, BaseException):
                    first_error = first_error or result
                    continue
                for (index, item_id, text), vector in zip(batch, result):
                    vectors[index] = vector
                    cache.put(namespace, item_id, text, vector)
            cache.commit()
            completed = min(wave_start + len(wave), len(missing))
            if completed == len(missing) or completed % 200 == 0:
                print(f"embedded {completed}/{len(missing)} uncached texts", flush=True)
            if first_error is not None:
                raise first_error

    if any(vector is None for vector in vectors):
        raise RuntimeError("embedding matrix is incomplete")
    matrix = np.vstack(vectors).astype(np.float32, copy=False)  # type: ignore[arg-type]
    if matrix.shape != (len(records), expected_dim):
        raise RuntimeError(f"unexpected embedding matrix shape: {matrix.shape}")
    return matrix


async def main() -> None:
    args = parse_args()
    if args.top_k <= 0 or args.batch_size <= 0 or args.concurrency <= 0:
        raise SystemExit("top-k, batch-size, and concurrency must be positive")
    if args.batch_size > 10:
        raise SystemExit("text-embedding-v4 accepts at most 10 texts per request")

    load_dotenv(args.env_file)
    base_url = os.getenv("EMBEDDING_BASE_URL", "").strip()
    api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
    model = os.getenv("EMBEDDING_MODEL", "").strip()
    expected_dim = int(os.getenv("EMBEDDING_DIM", "0"))
    if not all([base_url, api_key, model]) or expected_dim <= 0:
        raise SystemExit("EMBEDDING_BASE_URL/API_KEY/MODEL/DIM must be configured")

    products = pq.read_table(args.data_dir / "products.parquet").to_pylist()
    judgments = pq.read_table(args.data_dir / "judgments.parquet").to_pylist()
    manifest = json.loads((args.data_dir / "manifest.json").read_text(encoding="utf-8"))
    product_ids = np.asarray([str(row["product_id"]) for row in products], dtype=str)
    titles = [str(row["title"] or row["full_text"]) for row in products]
    full_texts = [str(row["full_text"] or row["title"]) for row in products]

    by_query: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in judgments:
        by_query[int(row["query_id"])].append(row)
    query_ids = sorted(by_query)
    queries = [str(by_query[query_id][0]["query"]) for query_id in query_ids]

    host = urlparse(base_url).netloc
    namespace = f"{host}|{model}|dim={expected_dim}"
    stats = EmbeddingRunStats()
    started = time.perf_counter()
    embedder = OpenAICompatibleEmbedder(base_url, api_key, model, expected_dim)
    with EmbeddingCache(args.cache) as cache:
        product_vectors = await _embed_records(
            list(zip(product_ids.tolist(), full_texts)),
            namespace=namespace,
            cache=cache,
            embedder=embedder,
            expected_dim=expected_dim,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            stats=stats,
        )
        query_vectors = await _embed_records(
            [(f"query:{query_id}", query) for query_id, query in zip(query_ids, queries)],
            namespace=namespace,
            cache=cache,
            embedder=embedder,
            expected_dim=expected_dim,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            stats=stats,
        )
    embedding_seconds = time.perf_counter() - started

    product_vectors = _normalize(product_vectors)
    query_vectors = _normalize(query_vectors)
    embedding_rankings = [
        _top_ids(scores, product_ids, args.top_k)
        for scores in query_vectors @ product_vectors.T
    ]

    baseline_started = time.perf_counter()
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        lowercase=True,
        strip_accents="unicode",
        sublinear_tf=True,
        dtype=np.float32,
        norm="l2",
    )
    baseline_products = vectorizer.fit_transform(titles)
    baseline_scores = (vectorizer.transform(queries) @ baseline_products.T).toarray()
    baseline_rankings = [
        _top_ids(scores, product_ids, args.top_k) for scores in baseline_scores
    ]
    baseline_seconds = time.perf_counter() - baseline_started

    exact_baseline: list[float] = []
    exact_embedding: list[float] = []
    broad_baseline: list[float] = []
    broad_embedding: list[float] = []
    exact_hit_baseline: list[float] = []
    exact_hit_embedding: list[float] = []
    per_query: list[dict[str, object]] = []
    for index, query_id in enumerate(query_ids):
        rows = by_query[query_id]
        exact = [str(row["product_id"]) for row in rows if row["esci_label"] == "E"]
        broad = [str(row["product_id"]) for row in rows if row["esci_label"] in {"E", "S"}]
        exact_baseline.append(recall_at_k(baseline_rankings[index], exact, args.top_k))
        exact_embedding.append(recall_at_k(embedding_rankings[index], exact, args.top_k))
        broad_baseline.append(recall_at_k(baseline_rankings[index], broad, args.top_k))
        broad_embedding.append(recall_at_k(embedding_rankings[index], broad, args.top_k))
        exact_hit_baseline.append(hit_rate_at_k(baseline_rankings[index], exact, args.top_k))
        exact_hit_embedding.append(hit_rate_at_k(embedding_rankings[index], exact, args.top_k))
        per_query.append(
            {
                "query_id": query_id,
                "query": queries[index],
                "exact_count": len(exact),
                "tfidf_exact_recall": exact_baseline[-1],
                "embedding_exact_recall": exact_embedding[-1],
                "tfidf_broad_recall": broad_baseline[-1],
                "embedding_broad_recall": broad_embedding[-1],
                "tfidf_top_10": "|".join(baseline_rankings[index][:10]),
                "embedding_top_10": "|".join(embedding_rankings[index][:10]),
            }
        )

    metrics = {
        "exact_recall": asdict(paired_estimate(exact_baseline, exact_embedding, seed=SEED)),
        "broad_recall": asdict(paired_estimate(broad_baseline, broad_embedding, seed=SEED + 1)),
        "exact_hit_rate": asdict(
            paired_estimate(exact_hit_baseline, exact_hit_embedding, seed=SEED + 2)
        ),
    }
    report = {
        "benchmark_version": 1,
        "dataset_manifest": manifest,
        "top_k": args.top_k,
        "baseline": "title TF-IDF word 1-2gram cosine",
        "candidate": f"{model} full-text embedding exact cosine",
        "embedding": {
            "provider_host": host,
            "model": model,
            "dimension": expected_dim,
            "cache_hits": stats.cache_hits,
            "cache_misses": stats.cache_misses,
            "api_requests_this_run": stats.api_requests,
            "api_input_tokens_this_run": stats.api_input_tokens,
            "embedding_seconds": embedding_seconds,
        },
        "baseline_seconds": baseline_seconds,
        "metrics": metrics,
        "limitations": [
            "Pilot scale is 5,000 products and 100 queries; expand only after validating cost and rate limits.",
            "ESCI judgments are pooled rather than exhaustive over every catalog item.",
            "Exact cosine isolates embedding quality and does not measure Qdrant ANN approximation or service latency.",
            "No reranker is configured, so this compares embedding-only retrieval with TF-IDF.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "per_query.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_query[0]))
        writer.writeheader()
        writer.writerows(per_query)

    exact = metrics["exact_recall"]
    broad = metrics["broad_recall"]
    markdown = f"""# Real embedding Top-{args.top_k} pilot

Dataset: {manifest['catalog_size']:,} products, {len(query_ids)} official ESCI test queries.

| Metric | TF-IDF | {model} | Absolute lift | Relative lift | Paired 95% CI |
|---|---:|---:|---:|---:|---:|
| Exact Recall@{args.top_k} | {exact['baseline']:.4f} | {exact['candidate']:.4f} | {exact['absolute_lift']:+.4f} | {exact['relative_lift']:+.2%} | [{exact['ci95_low']:+.4f}, {exact['ci95_high']:+.4f}] |
| Exact+Substitute Recall@{args.top_k} | {broad['baseline']:.4f} | {broad['candidate']:.4f} | {broad['absolute_lift']:+.4f} | {broad['relative_lift']:+.2%} | [{broad['ci95_low']:+.4f}, {broad['ci95_high']:+.4f}] |

Embedding API requests this run: {stats.api_requests}; input tokens reported: {stats.api_input_tokens}.
"""
    (args.output_dir / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    asyncio.run(main())
