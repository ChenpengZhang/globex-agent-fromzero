# Real embedding Recall@50 report

Run date: 2026-09-13. Model: `text-embedding-v4`, 1,024 dimensions. Seed: `20260912`.

## Outcome

The standalone benchmark successfully called the configured Alibaba Cloud Model Studio
embedding endpoint and compared exact cosine retrieval against the title TF-IDF baseline.
No application module, application Qdrant collection, or order data was read or written.

| Scale | Metric | TF-IDF | Real embedding | Absolute lift | Relative lift | Paired 95% CI |
|---|---|---:|---:|---:|---:|---:|
| 5,000 products / 100 queries | Exact Recall@50 | 0.7566 | 0.9129 | +0.1563 | +20.65% | [+0.1078, +0.2071] |
| 5,000 products / 100 queries | Exact+Substitute Recall@50 | 0.7073 | 0.8835 | +0.1762 | +24.90% | [+0.1270, +0.2269] |
| 10,000 products / 200 queries | Exact Recall@50 | 0.7456 | 0.8823 | +0.1367 | +18.33% | [+0.1016, +0.1729] |
| 10,000 products / 200 queries | Exact+Substitute Recall@50 | 0.6816 | 0.8423 | +0.1606 | +23.57% | [+0.1272, +0.1936] |

Exact HitRate@50 improved from 0.940 to 0.990 in the 5k run and from 0.925 to
0.975 in the 10k run.

Both expansions have paired confidence intervals entirely above zero. The gain decreased
moderately as the catalog doubled, but remained large and directionally consistent.

## Query-level behavior

| Scale | Exact improved / tied / regressed | Broad improved / tied / regressed |
|---|---:|---:|
| 5k / 100 | 46 / 47 / 7 | 65 / 28 / 7 |
| 10k / 200 | 92 / 93 / 15 | 134 / 49 / 17 |

Observed Exact-recall regressions in the 10k run include `small vacuum`, `fall truck`,
`d.c. 16v power cord`, `minnesota wild 3/4 zip`, and `tank m2`. This is evidence for
keeping a lexical retrieval channel rather than replacing it with embeddings outright.

## API and cache

| Run | Cache hits | Cache misses | API requests | Provider-reported input tokens | Wall time |
|---|---:|---:|---:|---:|---:|
| 5k / 100 | 0 | 5,100 | 510 | 1,078,819 | 106.6 s |
| 10k / 200 | 2,067 | 8,133 | 814 | 1,730,569 | 179.8 s |

The shared benchmark cache contains 13,233 verified 1,024-dimensional vectors and occupies
about 59.5 MiB. At a nominal Beijing-region rate of $0.072 per million tokens, the two
runs correspond to approximately $0.20 before any free quota or account-specific pricing.

## Methodology boundaries

- Data is the official ESCI US `small_version=1` test split. Every judged product for the
  selected queries is included, then seeded random distractors fill the target catalog size.
- The baseline is title word 1-2gram TF-IDF with cosine similarity.
- The candidate is `text-embedding-v4` over title, brand, color, bullet points, and
  description, ranked by exact cosine similarity.
- Exact cosine deliberately avoids Qdrant so this phase measures embedding quality without
  approximate-nearest-neighbor recall loss. Qdrant can be evaluated separately later.
- No reranker is configured, so these numbers measure embedding-only retrieval.
- ESCI judgments are pooled rather than exhaustive over every product in each sampled
  catalog. Results are recall of known judged positives.
- This is strong pilot evidence, not yet a 100k-catalog or production-traffic claim.

Generated machine-readable results remain under `results/embedding_pilot_5k/` and
`results/embedding_pilot_10k/`; they are intentionally ignored by Git.
