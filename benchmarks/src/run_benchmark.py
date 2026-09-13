from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer

from src.metrics import hit_rate_at_k, paired_estimate, recall_at_k


SEED = 20260912


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare a single sparse tower with a tiered proxy")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--candidate-k", type=int, default=400)
    parser.add_argument("--batch-size", type=int, default=16)
    return parser.parse_args()


def _top_indices(scores: np.ndarray, k: int, product_ids: np.ndarray) -> np.ndarray:
    k = min(k, scores.size)
    candidates = np.argpartition(scores, scores.size - k)[-k:]
    order = np.lexsort((product_ids[candidates], -scores[candidates]))
    return candidates[order]


def _dense_scores(query_matrix: csr_matrix, document_matrix: csr_matrix) -> np.ndarray:
    return (query_matrix @ document_matrix.T).toarray().astype(np.float32, copy=False)


def _fit_vectorizer(
    documents: list[str],
    *,
    analyzer: str,
    ngram_range: tuple[int, int],
    min_df: int,
    max_features: int,
) -> tuple[TfidfVectorizer, csr_matrix]:
    vectorizer = TfidfVectorizer(
        analyzer=analyzer,
        ngram_range=ngram_range,
        lowercase=True,
        strip_accents="unicode",
        min_df=min_df,
        max_features=max_features,
        sublinear_tf=True,
        dtype=np.float32,
        norm="l2",
    )
    return vectorizer, vectorizer.fit_transform(documents).tocsr()


def _retrieve(
    *,
    product_ids: np.ndarray,
    titles: list[str],
    full_texts: list[str],
    queries: list[str],
    top_k: int,
    candidate_k: int,
    batch_size: int,
) -> tuple[list[list[str]], list[list[str]], dict[str, float]]:
    timings: dict[str, float] = {}
    started = time.perf_counter()
    baseline_vectorizer, baseline_documents = _fit_vectorizer(
        titles,
        analyzer="word",
        ngram_range=(1, 2),
        min_df=2,
        max_features=200_000,
    )
    timings["fit_baseline_seconds"] = time.perf_counter() - started

    started = time.perf_counter()
    word_vectorizer, word_documents = _fit_vectorizer(
        full_texts,
        analyzer="word",
        ngram_range=(1, 2),
        min_df=2,
        max_features=250_000,
    )
    char_vectorizer, char_documents = _fit_vectorizer(
        titles,
        analyzer="char_wb",
        ngram_range=(3, 5),
        min_df=3,
        max_features=250_000,
    )
    timings["fit_project_proxy_seconds"] = time.perf_counter() - started

    baseline_results: list[list[str]] = []
    project_results: list[list[str]] = []
    baseline_query_seconds = 0.0
    project_query_seconds = 0.0

    for start in range(0, len(queries), batch_size):
        batch = queries[start : start + batch_size]
        tick = time.perf_counter()
        baseline_scores = _dense_scores(baseline_vectorizer.transform(batch), baseline_documents)
        baseline_query_seconds += time.perf_counter() - tick

        tick = time.perf_counter()
        word_scores = _dense_scores(word_vectorizer.transform(batch), word_documents)
        char_scores = _dense_scores(char_vectorizer.transform(batch), char_documents)
        project_query_seconds += time.perf_counter() - tick

        for row_index in range(len(batch)):
            baseline_idx = _top_indices(baseline_scores[row_index], top_k, product_ids)
            baseline_results.append(product_ids[baseline_idx].tolist())

            # Independent first-stage channels produce a broad pool.  The second-stage
            # score is deliberately fixed before evaluation: full product evidence is
            # dominant, typo-tolerant title evidence is secondary, and the original
            # title tower acts as a conservative lexical prior.
            word_idx = _top_indices(word_scores[row_index], candidate_k, product_ids)
            char_idx = _top_indices(char_scores[row_index], candidate_k, product_ids)
            title_idx = _top_indices(baseline_scores[row_index], candidate_k, product_ids)
            pool = np.unique(np.concatenate([word_idx, char_idx, title_idx]))
            rerank_score = (
                0.55 * word_scores[row_index, pool]
                + 0.30 * char_scores[row_index, pool]
                + 0.15 * baseline_scores[row_index, pool]
            )
            ranked_local = _top_indices(rerank_score, top_k, product_ids[pool])
            project_results.append(product_ids[pool[ranked_local]].tolist())

    timings["baseline_query_seconds"] = baseline_query_seconds
    timings["project_proxy_query_seconds"] = project_query_seconds
    timings["baseline_ms_per_query"] = 1_000 * baseline_query_seconds / len(queries)
    timings["project_proxy_ms_per_query"] = 1_000 * project_query_seconds / len(queries)
    return baseline_results, project_results, timings


def _estimate_dict(left: list[float], right: list[float], seed_offset: int) -> dict[str, float | None]:
    return asdict(paired_estimate(left, right, seed=SEED + seed_offset))


def main() -> None:
    args = parse_args()
    if args.candidate_k < args.top_k:
        raise SystemExit("candidate-k must be greater than or equal to top-k")

    products = pq.read_table(args.data_dir / "products.parquet").to_pylist()
    judgments = pq.read_table(args.data_dir / "judgments.parquet").to_pylist()
    manifest = json.loads((args.data_dir / "manifest.json").read_text(encoding="utf-8"))
    product_ids = np.asarray([row["product_id"] for row in products], dtype=str)
    titles = [row["title"] or row["full_text"] for row in products]
    full_texts = [row["full_text"] or row["title"] for row in products]

    by_query: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in judgments:
        by_query[int(row["query_id"])].append(row)
    query_ids = sorted(by_query)
    queries = [str(by_query[query_id][0]["query"]) for query_id in query_ids]

    baseline, project, timings = _retrieve(
        product_ids=product_ids,
        titles=titles,
        full_texts=full_texts,
        queries=queries,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        batch_size=args.batch_size,
    )

    per_query: list[dict[str, object]] = []
    metric_arrays: dict[str, tuple[list[float], list[float]]] = {
        "exact_recall": ([], []),
        "broad_recall": ([], []),
        "exact_hit_rate": ([], []),
        "broad_hit_rate": ([], []),
        "current_cap_exact_recall_at_8": ([], []),
    }
    for index, query_id in enumerate(query_ids):
        rows = by_query[query_id]
        exact = [str(row["product_id"]) for row in rows if row["esci_label"] == "E"]
        broad = [str(row["product_id"]) for row in rows if row["esci_label"] in {"E", "S"}]
        values = {
            "exact_recall": (
                recall_at_k(baseline[index], exact, args.top_k),
                recall_at_k(project[index], exact, args.top_k),
            ),
            "broad_recall": (
                recall_at_k(baseline[index], broad, args.top_k),
                recall_at_k(project[index], broad, args.top_k),
            ),
            "exact_hit_rate": (
                hit_rate_at_k(baseline[index], exact, args.top_k),
                hit_rate_at_k(project[index], exact, args.top_k),
            ),
            "broad_hit_rate": (
                hit_rate_at_k(baseline[index], broad, args.top_k),
                hit_rate_at_k(project[index], broad, args.top_k),
            ),
            "current_cap_exact_recall_at_8": (
                recall_at_k(baseline[index], exact, 8),
                recall_at_k(project[index], exact, 8),
            ),
        }
        for name, (left, right) in values.items():
            metric_arrays[name][0].append(left)
            metric_arrays[name][1].append(right)
        per_query.append(
            {
                "query_id": query_id,
                "query": queries[index],
                "exact_count": len(exact),
                "broad_count": len(broad),
                "baseline_exact_recall": values["exact_recall"][0],
                "project_exact_recall": values["exact_recall"][1],
                "baseline_broad_recall": values["broad_recall"][0],
                "project_broad_recall": values["broad_recall"][1],
                "baseline_top_10": "|".join(baseline[index][:10]),
                "project_top_10": "|".join(project[index][:10]),
            }
        )

    estimates = {
        name: _estimate_dict(left, right, offset)
        for offset, (name, (left, right)) in enumerate(metric_arrays.items())
    }
    report = {
        "benchmark_version": 1,
        "dataset_manifest": manifest,
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        "query_count": len(queries),
        "baseline": {
            "name": "single_sparse_tower",
            "definition": "one title TF-IDF word 1-2gram representation and cosine ranking",
        },
        "candidate": {
            "name": "tiered_retrieval_proxy",
            "definition": "union of three top-candidate channels, then fixed field-aware reranking",
            "weights": {"full_text_word": 0.55, "title_char": 0.30, "title_word": 0.15},
            "is_production_measurement": False,
        },
        "metrics": estimates,
        "timings": timings,
        "limitations": [
            "ESCI labels cover an official judged pool, not every relevant item in the sampled catalog.",
            "The candidate is an offline topology proxy because the configured DeepSeek endpoint has no embeddings API.",
            "The current application has a fixed first-stage cap of 8; Top-100 is a capacity-planning simulation.",
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

    exact = estimates["exact_recall"]
    broad = estimates["broad_recall"]
    markdown = f"""# Top-{args.top_k} product recall benchmark

Catalog: {manifest['catalog_size']:,} US products; queries: {len(queries)} official ESCI test queries.

| Metric | Single sparse tower | Tiered proxy | Absolute lift | Relative lift | Paired 95% CI |
|---|---:|---:|---:|---:|---:|
| Exact Recall@{args.top_k} | {exact['baseline']:.4f} | {exact['candidate']:.4f} | {exact['absolute_lift']:+.4f} | {exact['relative_lift']:+.2%} | [{exact['ci95_low']:+.4f}, {exact['ci95_high']:+.4f}] |
| Exact+Substitute Recall@{args.top_k} | {broad['baseline']:.4f} | {broad['candidate']:.4f} | {broad['absolute_lift']:+.4f} | {broad['relative_lift']:+.2%} | [{broad['ci95_low']:+.4f}, {broad['ci95_high']:+.4f}] |

This is an offline architecture proxy, not a production measurement. See `summary.json` and README for scope and limitations.
"""
    (args.output_dir / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
