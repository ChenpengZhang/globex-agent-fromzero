# Globex Top-100 product recall baseline

Run date: 2026-09-12. Seed: `20260912`.

## Decision summary

On the fixed 100,000-product / 500-query ESCI slice, the tiered retrieval proxy improves
Exact Recall@100 from **0.6361 to 0.7311**: **+9.49 percentage points**, or **+14.92% relative**.
The paired 95% bootstrap interval is **+7.86 to +11.29 points**.

When both Exact and Substitute products count as relevant, Recall@100 improves from
**0.5643 to 0.6567**: **+9.24 points**, or **+16.37% relative**. The paired 95% interval
is **+7.90 to +10.57 points**.

| Metric | Single sparse tower | Tiered proxy | Absolute lift | Relative lift |
|---|---:|---:|---:|---:|
| Exact Recall@100 | 0.6361 | 0.7311 | +0.0949 | +14.92% |
| Exact+Substitute Recall@100 | 0.5643 | 0.6567 | +0.0924 | +16.37% |
| Exact HitRate@100 | 0.8980 | 0.9480 | +0.0500 | +5.57% |
| Exact+Substitute HitRate@100 | 0.9240 | 0.9720 | +0.0480 | +5.19% |

At the application's current eight-candidate capacity, the same offline rankings yield
Exact Recall@8 of 0.2546 vs 0.3067 (+5.21 points). This is diagnostic only: it is not a
live application measurement.

## What “single tower” means here

The phrase is ambiguous in information retrieval. This benchmark makes it explicit and
reproducible: the baseline is one title-only sparse TF-IDF representation (word 1-2 grams)
with one cosine-ranking pass. It is best read as a **single-channel, single-stage baseline**,
not as a claim about a particular neural architecture.

The candidate is a capacity-planning proxy for the repository's intended tiered shape:

1. independently recall up to 400 candidates from full-text word, typo-tolerant title
   character, and title word channels;
2. union those candidates;
3. apply a fixed field-aware score (0.55 / 0.30 / 0.15);
4. return Top-100.

Weights were fixed before reading evaluation output; no test-label fitting is performed.

## Interpretation and guardrails

- The positive paired confidence intervals support a real improvement on this fixed slice.
- 194/500 queries improved on Exact Recall, 287 tied, and 19 regressed. Broad recall
  improved/tied/regressed on 261/207/32 queries. The proxy is not uniformly better.
- First-stage scoring was about 1.07 ms/query for the baseline and 13.92 ms/query for the
  proxy on this machine. These are single-run offline CPU measurements and exclude index
  serving/network latency, so they are directional, not an SLA.
- ESCI relevance judgments cover an official judged pool, not every potentially relevant
  product in the 100,000-item slice. The metric is therefore “recall of known judged
  positives,” not exhaustive catalog recall.
- This is **not yet a production uplift claim**. The current endpoint has no embedding API,
  no reranker is configured, the application catalog has only three products, and its
  first-stage cap is 8. Production validation requires an embedding-capable endpoint,
  a reranker (or an intentional hybrid implementation), a catalog index above 100 items,
  and online or fully judged evaluation.

The raw per-query output is generated at `results/per_query.csv`; machine-readable
aggregate output is generated at `results/summary.json`.
