from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


DEFAULT_SEED = 20260912


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a deterministic ESCI retrieval slice")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--queries", type=int, default=500)
    parser.add_argument("--catalog-size", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--locale", default="us")
    return parser.parse_args()


def _clean(value: object) -> str:
    return "" if value is None else " ".join(str(value).split())


def main() -> None:
    args = parse_args()
    examples_path = args.raw_dir / "shopping_queries_dataset_examples.parquet"
    products_path = args.raw_dir / "shopping_queries_dataset_products.parquet"
    if not examples_path.exists() or not products_path.exists():
        raise SystemExit("Raw ESCI parquet files are missing; see README.md")

    examples = pq.read_table(
        examples_path,
        columns=["query_id", "query", "product_id", "product_locale", "esci_label", "small_version", "split"],
    )
    mask = pc.and_(
        pc.equal(examples["product_locale"], args.locale),
        pc.and_(pc.equal(examples["small_version"], 1), pc.equal(examples["split"], "test")),
    )
    examples = examples.filter(mask)

    rows_by_query: dict[int, list[dict[str, object]]] = defaultdict(list)
    query_text: dict[int, str] = {}
    for row in examples.to_pylist():
        query_id = int(row["query_id"])
        rows_by_query[query_id].append(row)
        query_text[query_id] = _clean(row["query"])

    eligible = sorted(
        query_id
        for query_id, rows in rows_by_query.items()
        if any(row["esci_label"] == "E" for row in rows)
    )
    if args.queries > len(eligible):
        raise SystemExit(f"requested {args.queries} queries, only {len(eligible)} are eligible")
    rng = random.Random(args.seed)
    selected_query_ids = sorted(rng.sample(eligible, args.queries))
    selected_rows = [row for query_id in selected_query_ids for row in rows_by_query[query_id]]
    judged_ids = {str(row["product_id"]) for row in selected_rows}

    products = pq.read_table(
        products_path,
        columns=[
            "product_id", "product_title", "product_description", "product_bullet_point",
            "product_brand", "product_color", "product_locale",
        ],
    )
    products = products.filter(pc.equal(products["product_locale"], args.locale))
    all_ids = products["product_id"].to_pylist()
    available_ids = set(all_ids)
    missing_judged = sorted(judged_ids - available_ids)
    if missing_judged:
        raise SystemExit(f"{len(missing_judged)} judged products are absent from the product table")
    if args.catalog_size < len(judged_ids):
        raise SystemExit(
            f"catalog-size {args.catalog_size} is smaller than {len(judged_ids)} judged products"
        )

    distractor_pool = [product_id for product_id in all_ids if product_id not in judged_ids]
    selected_ids = judged_ids | set(
        rng.sample(distractor_pool, args.catalog_size - len(judged_ids))
    )
    products = products.filter(pc.is_in(products["product_id"], value_set=pa.array(selected_ids)))

    compact_products: list[dict[str, str]] = []
    for row in products.to_pylist():
        title = _clean(row["product_title"])
        brand = _clean(row["product_brand"])
        color = _clean(row["product_color"])
        bullets = _clean(row["product_bullet_point"])
        description = _clean(row["product_description"])
        full_text = " ".join(part for part in [title, brand, color, bullets, description] if part)[:1_500]
        compact_products.append(
            {"product_id": str(row["product_id"]), "title": title, "full_text": full_text}
        )
    compact_products.sort(key=lambda row: row["product_id"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(compact_products), args.output_dir / "products.parquet")
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "query_id": int(row["query_id"]),
                    "query": query_text[int(row["query_id"])],
                    "product_id": str(row["product_id"]),
                    "esci_label": str(row["esci_label"]),
                }
                for row in selected_rows
            ]
        ),
        args.output_dir / "judgments.parquet",
    )
    manifest = {
        "dataset": "Amazon Shopping Queries Dataset (ESCI)",
        "locale": args.locale,
        "official_split": "test",
        "official_task_flag": "small_version=1",
        "seed": args.seed,
        "query_count": len(selected_query_ids),
        "catalog_size": len(compact_products),
        "judgment_count": len(selected_rows),
        "judged_product_count": len(judged_ids),
        "relevant_exact": "E",
        "relevant_broad": ["E", "S"],
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
