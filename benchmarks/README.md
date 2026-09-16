# Product recall benchmark

This directory is intentionally isolated from `app/`. It downloads public evaluation
data, creates a deterministic catalog slice, and compares a transparent single-channel
baseline with a tiered retrieval proxy. No application core file is imported or modified.

## Reproduce

From this directory:

```bash
uv sync
PYTHONPATH=. .venv/bin/python -m src.download_esci
PYTHONPATH=. .venv/bin/python -m src.prepare_esci --queries 500 --catalog-size 100000
PYTHONPATH=. .venv/bin/python -m src.run_benchmark --top-k 100 --candidate-k 400
PYTHONPATH=. .venv/bin/pytest -q
```

## Real embedding pilot

The real-embedding runner reads the parent project's `EMBEDDING_*` variables, but owns
its dataset, SQLite vector cache, exact-cosine search, and result files. It does not import
or write anything under `app/`, and it does not share the application's Qdrant collection.

```bash
PYTHONPATH=. .venv/bin/python -m src.prepare_esci \
  --queries 100 --catalog-size 5000 --output-dir data/processed_pilot_5k
PYTHONPATH=. .venv/bin/python -m src.run_embedding_benchmark \
  --data-dir data/processed_pilot_5k --top-k 50
```

Vectors are committed to `data/cache/embeddings.sqlite3` after each small wave, so a
rate-limit, network failure, or interrupted process can resume without paying to embed
completed texts again. The first pilot deliberately uses exact cosine rather than Qdrant:
this measures model quality without mixing in approximate-index recall. Qdrant should be
benchmarked separately after the embedding model is selected.

The checked-in `REAL_EMBEDDING_REPORT.md` records the completed 5k/100-query and
10k/200-query runs. Generated JSON, Markdown, and per-query CSV outputs stay under
`results/` and are ignored by Git.

The download script uses the official Amazon Science GitHub files and verifies the exact
SHA-256 values used for the recorded run. Raw/processed data and generated results are
ignored by Git; source, lockfile, methodology, fixed query examples, and the baseline
report are versionable.

## Evaluation protocol

- Dataset: official Amazon ESCI, `small_version=1`, US locale, official `test` split.
- Query sample: 500 query IDs selected with seed `20260912`.
- Catalog: every judged product for those queries plus seeded random US distractors to
  exactly 100,000 products.
- Exact relevance: label `E`.
- Broad relevance: labels `E` or `S`.
- Primary metric: macro Recall@100 (each query has equal weight).
- Secondary metric: HitRate@100.
- Uncertainty: 2,000-query paired bootstrap over candidate-minus-baseline differences.

See `DATA_INVENTORY.md` for repository findings and `BASELINE_REPORT.md` for results and
limitations. `examples/esci_query_sample.jsonl` contains real benchmark queries chosen to
cover both improvements and regressions, ready for review or replacement.

## Serial versus parallel search latency

The latency runner uses five multi-product user requests. For each request it executes the
same independent search branches in two ways: serially as a single-agent proxy, then
concurrently as an isolated parallel-dispatch prototype. Every branch makes a live
embedding request and performs exact-cosine Top-50 search against the cached 10k catalog.

```bash
PYTHONPATH=. .venv/bin/python -m src.run_agent_latency_benchmark \
  --data-dir data/processed_pilot_10k --top-k 50 --repeats 3
```

This is deliberately not described as an end-to-end result for the current application.
The current `task_dispatch` awaits one specialist reply and has no explicit multi-dispatch
parallelism. The runner measures the retrieval-stage concurrency opportunity only; it
excludes LLM decomposition/routing and final answer generation, and imports no `app` code.
The completed five-case live run is summarized in `AGENT_LATENCY_REPORT.md`.

If the embedding provider is temporarily unavailable, `--backend controlled` runs an
explicitly labelled architecture control. It combines deterministic 170–270 ms I/O waits
with the same real 10k-vector exact search. Its result is an upper-bound/scheduler check,
not live-provider or end-to-end application evidence.
