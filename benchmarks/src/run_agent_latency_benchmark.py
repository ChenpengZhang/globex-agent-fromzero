from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np
import pyarrow.parquet as pq
from dotenv import load_dotenv

from src.agent_latency import (
    LatencyPair,
    SearchResult,
    percentile,
    run_parallel,
    run_serial,
    summarize_pairs,
)
from src.embedding_cache import EmbeddingCache
from src.run_embedding_benchmark import EmbeddingRunStats, OpenAICompatibleEmbedder


SEED = 20260913


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare serial and parallel execution of independent product-search branches"
        )
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("examples/agent_latency_cases.json"),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/processed_pilot_10k"),
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("data/cache/embeddings.sqlite3"),
    )
    parser.add_argument("--env-file", type=Path, default=Path("../.env"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/agent_latency"),
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument(
        "--backend",
        choices=("live", "controlled"),
        default="live",
        help="live embedding API, or a calibrated deterministic I/O control",
    )
    parser.add_argument("--controlled-min-ms", type=float, default=170.0)
    parser.add_argument("--controlled-max-ms", type=float, default=270.0)
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, object]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or len(cases) != 5:
        raise ValueError("the latency benchmark requires exactly five cases")
    seen: set[str] = set()
    for case in cases:
        case_id = str(case.get("case_id", "")).strip()
        request = str(case.get("user_request", "")).strip()
        branches = case.get("search_branches")
        if not case_id or case_id in seen or not request:
            raise ValueError("each case needs a unique case_id and a user_request")
        if not isinstance(branches, list) or len(branches) < 2:
            raise ValueError(f"{case_id} needs at least two independent search branches")
        if any(not isinstance(branch, str) or not branch.strip() for branch in branches):
            raise ValueError(f"{case_id} contains an invalid search branch")
        seen.add(case_id)
    return cases


def normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise RuntimeError("zero vector found")
    return matrix / norms


def load_catalog_matrix(
    *,
    data_dir: Path,
    cache_path: Path,
    namespace: str,
    expected_dim: int,
) -> tuple[np.ndarray, np.ndarray]:
    products = pq.read_table(data_dir / "products.parquet").to_pylist()
    product_ids = np.asarray([str(row["product_id"]) for row in products], dtype=str)
    vectors: list[np.ndarray] = []
    missing = 0
    with EmbeddingCache(cache_path) as cache:
        for row in products:
            product_id = str(row["product_id"])
            text = str(row["full_text"] or row["title"])
            vector = cache.get(namespace, product_id, text)
            if vector is None:
                missing += 1
            else:
                vectors.append(vector)
    if missing:
        raise RuntimeError(
            f"{missing} catalog vectors are absent from the benchmark cache; "
            "run src.run_embedding_benchmark for this data directory first"
        )
    matrix = np.vstack(vectors).astype(np.float32, copy=False)
    if matrix.shape != (len(product_ids), expected_dim):
        raise RuntimeError(f"unexpected catalog matrix shape: {matrix.shape}")
    return product_ids, normalize(matrix)


class LiveSearchBackend:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        embedder: OpenAICompatibleEmbedder,
        product_ids: np.ndarray,
        product_vectors: np.ndarray,
        top_k: int,
        stats: EmbeddingRunStats,
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._product_ids = product_ids
        self._product_vectors = product_vectors
        self._top_k = top_k
        self._stats = stats

    async def search(self, query: str) -> SearchResult:
        started = time.perf_counter()
        vector = (
            await self._embedder.embed_batch(self._client, [query], self._stats)
        )[0]
        normalized = normalize(vector.reshape(1, -1))[0]
        scores = normalized @ self._product_vectors.T
        k = min(self._top_k, scores.size)
        candidates = np.argpartition(scores, scores.size - k)[-k:]
        order = np.lexsort((self._product_ids[candidates], -scores[candidates]))
        top_ids = tuple(self._product_ids[candidates[order]].tolist())
        return SearchResult(
            query=query,
            top_product_ids=top_ids,
            elapsed_ms=(time.perf_counter() - started) * 1_000,
        )


class ControlledSearchBackend:
    """Deterministic I/O control for architecture checks when the provider is unavailable."""

    def __init__(
        self,
        *,
        product_ids: np.ndarray,
        product_vectors: np.ndarray,
        top_k: int,
        min_ms: float,
        max_ms: float,
    ) -> None:
        if min_ms <= 0 or max_ms < min_ms:
            raise ValueError("controlled latency bounds are invalid")
        self._product_ids = product_ids
        self._product_vectors = product_vectors
        self._top_k = top_k
        self._min_ms = min_ms
        self._range_ms = max_ms - min_ms

    async def search(self, query: str) -> SearchResult:
        digest = hashlib.sha256(query.encode("utf-8")).digest()
        fraction = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        delay_ms = self._min_ms + self._range_ms * fraction
        started = time.perf_counter()
        await asyncio.sleep(delay_ms / 1_000)
        seed = int.from_bytes(digest[8:16], "big")
        vector = np.random.default_rng(seed).standard_normal(
            self._product_vectors.shape[1], dtype=np.float32
        )
        normalized = normalize(vector.reshape(1, -1))[0]
        scores = normalized @ self._product_vectors.T
        k = min(self._top_k, scores.size)
        candidates = np.argpartition(scores, scores.size - k)[-k:]
        order = np.lexsort((self._product_ids[candidates], -scores[candidates]))
        top_ids = tuple(self._product_ids[candidates[order]].tolist())
        return SearchResult(
            query=query,
            top_product_ids=top_ids,
            elapsed_ms=(time.perf_counter() - started) * 1_000,
        )


async def timed_execution(queries: list[str], search, *, parallel: bool):
    started = time.perf_counter()
    if parallel:
        results = await run_parallel(queries, search)
    else:
        results = await run_serial(queries, search)
    return (time.perf_counter() - started) * 1_000, results


def write_outputs(
    *,
    output_dir: Path,
    cases: list[dict[str, object]],
    pairs: list[LatencyPair],
    rows: list[dict[str, object]],
    summary: dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    by_case: dict[str, list[LatencyPair]] = defaultdict(list)
    for pair in pairs:
        by_case[pair.case_id].append(pair)
    case_by_id = {str(case["case_id"]): case for case in cases}
    report_lines = [
        "# Agent search latency benchmark",
        "",
        "This is a live search-execution benchmark. The serial baseline and parallel",
        "prototype run identical embedding + exact-cosine Top-50 branches over the",
        "same 10k-product catalog. It excludes LLM routing and final response generation.",
        "The application currently has specialist dispatch but no explicit parallel dispatch.",
        "",
        "| Case | Branches | Serial p50 | Parallel p50 | Speedup | Reduction |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for case_id, case_pairs in by_case.items():
        serial = [pair.serial_ms for pair in case_pairs]
        parallel = [pair.parallel_ms for pair in case_pairs]
        serial_p50 = percentile(serial, 50)
        parallel_p50 = percentile(parallel, 50)
        branch_count = len(case_by_id[case_id]["search_branches"])  # type: ignore[arg-type]
        report_lines.append(
            f"| {case_id} | {branch_count} | {serial_p50:.1f} ms | "
            f"{parallel_p50:.1f} ms | {serial_p50 / parallel_p50:.2f}x | "
            f"{(1 - parallel_p50 / serial_p50) * 100:.1f}% |"
        )
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    report_lines.extend(
        [
            "",
            "## Aggregate",
            "",
            f"- Paired runs: {int(metrics['pair_count'])}",
            f"- Aggregate speedup: {metrics['aggregate_speedup']:.2f}x",
            f"- Mean latency reduction: {metrics['mean_latency_reduction'] * 100:.1f}%",
            "- 95% paired-bootstrap interval for mean reduction: "
            f"[{metrics['latency_reduction_ci95_low'] * 100:.1f}%, "
            f"{metrics['latency_reduction_ci95_high'] * 100:.1f}%]",
            "",
            "## Interpretation boundary",
            "",
            "The result isolates concurrency in independent retrieval branches. It is not an",
            "end-to-end claim for the current MainAgent because LLM decomposition, dispatch,",
            "reranking, answer synthesis, provider rate limits, and shared-session locking are",
            "outside this harness. The prototype does not modify or import application code.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")


async def main() -> None:
    args = parse_args()
    if args.repeats <= 0 or args.top_k <= 0:
        raise SystemExit("repeats and top-k must be positive")
    cases = load_cases(args.cases)

    load_dotenv(args.env_file)
    base_url = os.getenv("EMBEDDING_BASE_URL", "").strip()
    api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
    model = os.getenv("EMBEDDING_MODEL", "").strip()
    expected_dim = int(os.getenv("EMBEDDING_DIM", "0"))
    if not all([base_url, model]) or expected_dim <= 0:
        raise SystemExit("EMBEDDING_BASE_URL/MODEL/DIM must be configured")
    if args.backend == "live" and not api_key:
        raise SystemExit("EMBEDDING_API_KEY must be configured for the live backend")

    host = urlparse(base_url).netloc
    namespace = f"{host}|{model}|dim={expected_dim}"
    product_ids, product_vectors = load_catalog_matrix(
        data_dir=args.data_dir,
        cache_path=args.cache,
        namespace=namespace,
        expected_dim=expected_dim,
    )
    stats = EmbeddingRunStats()
    embedder = OpenAICompatibleEmbedder(base_url, api_key, model, expected_dim)
    timeout = httpx.Timeout(60.0, connect=20.0)
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
    pairs: list[LatencyPair] = []
    rows: list[dict[str, object]] = []
    rng = random.Random(SEED)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        if args.backend == "live":
            backend = LiveSearchBackend(
                client=client,
                embedder=embedder,
                product_ids=product_ids,
                product_vectors=product_vectors,
                top_k=args.top_k,
                stats=stats,
            )
        else:
            backend = ControlledSearchBackend(
                product_ids=product_ids,
                product_vectors=product_vectors,
                top_k=args.top_k,
                min_ms=args.controlled_min_ms,
                max_ms=args.controlled_max_ms,
            )
        await backend.search("benchmark warmup query")
        for repeat in range(1, args.repeats + 1):
            shuffled = list(cases)
            rng.shuffle(shuffled)
            for case_index, case in enumerate(shuffled):
                case_id = str(case["case_id"])
                queries = [str(query) for query in case["search_branches"]]  # type: ignore[union-attr]
                parallel_first = (repeat + case_index) % 2 == 0
                measurements: dict[str, tuple[float, list[SearchResult]]] = {}
                for mode in (["parallel", "serial"] if parallel_first else ["serial", "parallel"]):
                    measurements[mode] = await timed_execution(
                        queries,
                        backend.search,
                        parallel=mode == "parallel",
                    )
                serial_ms, serial_results = measurements["serial"]
                parallel_ms, parallel_results = measurements["parallel"]
                if [result.query for result in serial_results] != [
                    result.query for result in parallel_results
                ]:
                    raise RuntimeError("serial and parallel runs returned different query order")
                pair = LatencyPair(case_id, repeat, serial_ms, parallel_ms)
                pairs.append(pair)
                rows.append(
                    {
                        **asdict(pair),
                        "branch_count": len(queries),
                        "speedup": pair.speedup,
                        "latency_reduction": pair.reduction,
                        "first_mode": "parallel" if parallel_first else "serial",
                        "serial_branch_ms": "|".join(
                            f"{result.elapsed_ms:.3f}" for result in serial_results
                        ),
                        "parallel_branch_ms": "|".join(
                            f"{result.elapsed_ms:.3f}" for result in parallel_results
                        ),
                    }
                )
                print(
                    f"repeat={repeat} case={case_id} serial={serial_ms:.1f}ms "
                    f"parallel={parallel_ms:.1f}ms speedup={pair.speedup:.2f}x",
                    flush=True,
                )

    metrics = summarize_pairs(pairs, seed=SEED)
    summary: dict[str, object] = {
        "benchmark_version": 1,
        "backend": args.backend,
        "scope": (
            "live embedding plus exact-cosine Top-K search over independent branches"
            if args.backend == "live"
            else "calibrated deterministic I/O plus exact-cosine Top-K architecture control"
        ),
        "current_application_has_explicit_parallel_dispatch": False,
        "baseline": "single-agent proxy: identical search branches executed serially",
        "candidate": "parallel-dispatch prototype: identical branches executed concurrently",
        "excludes": [
            "LLM request decomposition",
            "MainAgent and SearchAgent model calls",
            "reranking",
            "final answer synthesis",
        ],
        "case_count": len(cases),
        "repeats": args.repeats,
        "catalog_size": len(product_ids),
        "top_k": args.top_k,
        "provider_host": host,
        "embedding_model": model,
        "embedding_dimension": expected_dim,
        "controlled_latency_ms": (
            [args.controlled_min_ms, args.controlled_max_ms]
            if args.backend == "controlled"
            else None
        ),
        "api_requests_including_warmup_and_retries": stats.api_requests,
        "api_input_tokens": stats.api_input_tokens,
        "metrics": metrics,
    }
    write_outputs(
        output_dir=args.output_dir,
        cases=cases,
        pairs=pairs,
        rows=rows,
        summary=summary,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
