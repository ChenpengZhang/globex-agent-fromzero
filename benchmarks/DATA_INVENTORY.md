# Repository data inventory

Inventory date: 2026-09-12.

## Original repository (`globex-agent`)

| Asset | Quantity | Location | Assessment |
|---|---:|---|---|
| Seed products | 60 SPUs / 65 SKUs | `app/infrastructure/persistence/seed_products.py` | Useful for regression, too small for Top-100 |
| Product relevance cases | 67 queries / 99 relevance assignments | `eval/product_recall.jsonl` | 55 lexical and 12 semantic queries; single-author labels |
| Category relevance cases | 22 queries | `eval/category_recall.jsonl` | Useful for knowledge retrieval regression |
| Knowledge documents | 5 Markdown files / 177 lines | `knowledge/` | Travel, digital, home, outdoor, cross-border topics |

The original repository's own report records Recall@8 of 0.978 for embedding-only and
0.871 for keyword 2-gram on its 60-product catalog. That is historical repository
evidence, not a rerun in this benchmark. The report also documents that no reranker was
configured, so its `embedding_rerank` row was effectively embedding-only.

## From-zero repository (`globex-agent-fromzero`)

| Asset | Quantity | Assessment |
|---|---:|---|
| Seed products | 3 SPUs / 4 SKUs, one category | Insufficient for Top-100 |
| Product relevance cases | 0 | No product recall evaluation set |
| Knowledge documents | 1 Markdown file / 36 lines | Insufficient for broad category evaluation |
| Local product vector index | Metadata/lock only; no collection data | No usable indexed product corpus |
| Local category index | One small SQLite collection | Usable only for the single knowledge document |

The configured base endpoint is an LLM chat endpoint. A live probe returned HTTP 404
for `/embeddings`, so the current product search would follow its designed keyword
fallback. The application also fixes first-stage vector recall at 8 candidates, which
cannot support a genuine Top-100 result without a future capacity change.

## External benchmark data

The benchmark uses Amazon Science's Shopping Queries Dataset (ESCI), released under
Apache-2.0:

- 1,814,924 products in the official product parquet.
- 2,621,288 query-product judgments in the official examples parquet.
- Labels: Exact, Substitute, Complement, Irrelevant.
- Local download: 49 MiB judgments + 1.03 GiB products.
- Deterministic evaluation slice: 100,000 US products, 500 official test queries,
  10,199 judgments, and 10,162 judged products.

Primary source: <https://github.com/amazon-science/esci-data>

Paper: <https://arxiv.org/abs/2206.06588>
