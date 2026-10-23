"""Pack and verify existing public book data without crawling or reranking."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_all_pages(payload: dict, data_dir: Path) -> dict:
    if payload["count"] != len(payload["books"]):
        raise ValueError("All-books count differs from actual records")
    version = hashlib.sha256(encoded(payload)).hexdigest()[:16]
    folder = data_dir / "all-pages" / version
    folder.mkdir(parents=True, exist_ok=True)
    for page in range(max(1, math.ceil(payload["count"] / 100))):
        content = encoded({"books": payload["books"][page * 100:(page + 1) * 100]})
        target = folder / f"{page + 1}.json"
        if target.exists() and target.read_bytes() != content:
            raise ValueError("Content-addressed book page changed")
        if not target.exists():
            target.write_bytes(content)
    return {"root": f"data/all-pages/{version}/", "count": payload["count"], "page_size": 100}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    original = root / "data/all-books.json"
    raw = original.read_bytes()
    payload = json.loads(raw)
    catalog_file = root / "data/catalog.json"
    catalog = json.loads(catalog_file.read_bytes())
    categories_hash = hashlib.sha256(encoded(catalog["categories"])).hexdigest()
    receipt_file = root / "results/pages-shards-verification.json"
    if receipt_file.exists():
        previous = json.loads(receipt_file.read_bytes())
        assert hashlib.sha256(raw).hexdigest() == previous["original_sha256"]
        assert categories_hash == previous["categories_sha256"]
    if args.pack:
        catalog["all_books"]["paged"] = write_all_pages(payload, root / "data")
        catalog_file.write_bytes(encoded(catalog))
    descriptor = catalog["all_books"]["paged"]
    assert descriptor["count"] == catalog["all_books"]["count"] == payload["count"]
    assert descriptor["page_size"] == 100
    pages = max(1, math.ceil(payload["count"] / 100))
    total_bytes = 0
    for page in range(pages):
        content = (root / descriptor["root"] / f"{page + 1}.json").read_bytes()
        assert json.loads(content)["books"] == payload["books"][page * 100:(page + 1) * 100]
        total_bytes += len(content)
    assert original.read_bytes() == raw
    first = root / descriptor["root"] / "1.json"
    receipt = {"original_sha256": hashlib.sha256(raw).hexdigest(), "categories_sha256": categories_hash,
               "books_verified_in_order": payload["count"], "pages": pages, "page_bytes": total_bytes,
               "legacy_json_bytes": len(raw), "catalog_bytes": catalog_file.stat().st_size,
               "first_page_bytes": first.stat().st_size,
               "initial_json_bytes": catalog_file.stat().st_size + first.stat().st_size,
               "page_root": descriptor["root"], "legacy_url_preserved": catalog["all_books"]["file"],
               "notes": "Exact records/order; only optional paging metadata added to catalog. Uncompressed file sizes, not measured transfer, latency, heap or energy."}
    receipt_file.parent.mkdir(exist_ok=True)
    receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
