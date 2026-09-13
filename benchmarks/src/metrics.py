from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    if k <= 0 or not relevant:
        return 0.0
    return len(set(_unique(retrieved)[:k]) & set(relevant)) / len(set(relevant))


def hit_rate_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    return float(recall_at_k(retrieved, relevant, k) > 0)


@dataclass(frozen=True)
class PairedEstimate:
    baseline: float
    candidate: float
    absolute_lift: float
    relative_lift: float | None
    ci95_low: float
    ci95_high: float


def paired_estimate(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    seed: int,
    bootstrap_samples: int = 2_000,
) -> PairedEstimate:
    left = np.asarray(baseline, dtype=np.float64)
    right = np.asarray(candidate, dtype=np.float64)
    if left.shape != right.shape or left.size == 0:
        raise ValueError("paired metric arrays must be non-empty and have the same shape")

    left_mean = float(left.mean())
    right_mean = float(right.mean())
    lift = right_mean - left_mean
    relative = None if left_mean == 0 else lift / left_mean

    rng = np.random.default_rng(seed)
    indices = rng.integers(0, left.size, size=(bootstrap_samples, left.size))
    deltas = (right[indices] - left[indices]).mean(axis=1)
    low, high = np.quantile(deltas, [0.025, 0.975])
    return PairedEstimate(
        baseline=left_mean,
        candidate=right_mean,
        absolute_lift=lift,
        relative_lift=relative,
        ci95_low=float(low),
        ci95_high=float(high),
    )
