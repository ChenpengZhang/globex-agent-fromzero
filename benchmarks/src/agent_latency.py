from __future__ import annotations

import asyncio
import statistics
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SearchResult:
    query: str
    top_product_ids: tuple[str, ...]
    elapsed_ms: float


@dataclass(frozen=True)
class LatencyPair:
    case_id: str
    repeat: int
    serial_ms: float
    parallel_ms: float

    @property
    def speedup(self) -> float:
        return self.serial_ms / self.parallel_ms

    @property
    def reduction(self) -> float:
        return 1.0 - self.parallel_ms / self.serial_ms


SearchCallable = Callable[[str], Awaitable[SearchResult]]


async def run_serial(
    queries: Sequence[str],
    search: SearchCallable,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    for query in queries:
        results.append(await search(query))
    return results


async def run_parallel(
    queries: Sequence[str],
    search: SearchCallable,
) -> list[SearchResult]:
    return list(await asyncio.gather(*(search(query) for query in queries)))


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    return float(np.percentile(np.asarray(values, dtype=np.float64), quantile))


def summarize_pairs(
    pairs: Sequence[LatencyPair],
    *,
    seed: int,
    bootstrap_samples: int = 2_000,
) -> dict[str, float]:
    if not pairs:
        raise ValueError("pairs cannot be empty")
    serial = np.asarray([pair.serial_ms for pair in pairs], dtype=np.float64)
    parallel = np.asarray([pair.parallel_ms for pair in pairs], dtype=np.float64)
    if np.any(serial <= 0) or np.any(parallel <= 0):
        raise ValueError("latencies must be positive")

    reduction = 1.0 - parallel / serial
    rng = np.random.default_rng(seed)
    sample_indices = rng.integers(
        0,
        len(pairs),
        size=(bootstrap_samples, len(pairs)),
    )
    boot_reductions = reduction[sample_indices].mean(axis=1)
    low, high = np.percentile(boot_reductions, [2.5, 97.5])
    return {
        "pair_count": float(len(pairs)),
        "serial_mean_ms": float(serial.mean()),
        "serial_median_ms": float(statistics.median(serial.tolist())),
        "parallel_mean_ms": float(parallel.mean()),
        "parallel_median_ms": float(statistics.median(parallel.tolist())),
        "mean_speedup": float((serial / parallel).mean()),
        "aggregate_speedup": float(serial.sum() / parallel.sum()),
        "mean_latency_reduction": float(reduction.mean()),
        "latency_reduction_ci95_low": float(low),
        "latency_reduction_ci95_high": float(high),
    }
