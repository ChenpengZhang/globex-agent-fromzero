import asyncio

import pytest

from src.agent_latency import (
    LatencyPair,
    SearchResult,
    run_parallel,
    run_serial,
    summarize_pairs,
)
from src.run_agent_latency_benchmark import ControlledSearchBackend, load_cases


def test_latency_modes_keep_input_order() -> None:
    async def search(query: str) -> SearchResult:
        await asyncio.sleep({"slow": 0.02, "fast": 0.001}[query])
        return SearchResult(query, (query,), 1.0)

    async def exercise() -> None:
        queries = ["slow", "fast"]
        serial = await run_serial(queries, search)
        parallel = await run_parallel(queries, search)
        assert [result.query for result in serial] == queries
        assert [result.query for result in parallel] == queries

    asyncio.run(exercise())


def test_summary_uses_paired_latency_reduction() -> None:
    pairs = [
        LatencyPair("a", 1, 100.0, 50.0),
        LatencyPair("b", 1, 200.0, 100.0),
    ]
    summary = summarize_pairs(pairs, seed=7, bootstrap_samples=100)
    assert summary["aggregate_speedup"] == pytest.approx(2.0)
    assert summary["mean_latency_reduction"] == pytest.approx(0.5)


def test_five_latency_cases_are_valid() -> None:
    cases = load_cases(__import__("pathlib").Path("examples/agent_latency_cases.json"))
    assert len(cases) == 5
    assert all(len(case["search_branches"]) >= 2 for case in cases)


def test_controlled_backend_is_deterministic() -> None:
    import numpy as np

    product_ids = np.asarray(["a", "b"])
    product_vectors = np.eye(2, dtype=np.float32)
    backend = ControlledSearchBackend(
        product_ids=product_ids,
        product_vectors=product_vectors,
        top_k=1,
        min_ms=0.1,
        max_ms=0.1,
    )

    async def exercise() -> None:
        first = await backend.search("same")
        second = await backend.search("same")
        assert first.top_product_ids == second.top_product_ids

    asyncio.run(exercise())
