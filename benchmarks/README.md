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
