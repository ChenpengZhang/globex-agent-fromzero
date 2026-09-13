from __future__ import annotations

import argparse
import hashlib
import os
import urllib.request
from pathlib import Path


FILES = {
    "shopping_queries_dataset_examples.parquet": {
        "url": "https://github.com/amazon-science/esci-data/raw/main/shopping_queries_dataset/shopping_queries_dataset_examples.parquet",
        "sha256": "4a735b693b4a424a6fc67f5be6e4c811495c488bbf66d02a602d308b2744263a",
    },
    "shopping_queries_dataset_products.parquet": {
        "url": "https://github.com/amazon-science/esci-data/raw/main/shopping_queries_dataset/shopping_queries_dataset_products.parquet",
        "sha256": "25124442d064d64b26f74082d6fa09438d679efc0c183cf28d19064a2b65a265",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _progress(name: str):
    last_percent = -1

    def report(blocks: int, block_size: int, total: int) -> None:
        nonlocal last_percent
        if total <= 0:
            return
        percent = min(100, blocks * block_size * 100 // total)
        if percent >= last_percent + 5 or percent == 100:
            print(f"{name}: {percent}%", flush=True)
            last_percent = percent

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the official Amazon ESCI parquet files")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for name, metadata in FILES.items():
        destination = args.output_dir / name
        expected = metadata["sha256"]
        if destination.exists() and _sha256(destination) == expected:
            print(f"{name}: already present and verified")
            continue
        partial = destination.with_suffix(destination.suffix + ".part")
        urllib.request.urlretrieve(metadata["url"], partial, _progress(name))
        actual = _sha256(partial)
        if actual != expected:
            raise SystemExit(f"checksum mismatch for {name}: expected {expected}, got {actual}")
        os.replace(partial, destination)
        print(f"{name}: verified {actual}")


if __name__ == "__main__":
    main()
