from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from .ranking import integrated_score
from .storage import Database


TAG_FIELDS = (
    "douban_id",
    "title",
    "rating",
    "votes",
    "score",
    "url",
    "metadata",
    "updated_at",
)


def snapshot_legacy_tags(database: Database, legacy_root: Path) -> dict[str, int]:
    tags_dir = legacy_root / "Tags"
    if not tags_dir.is_dir():
        raise FileNotFoundError(f"缺少历史标签目录: {tags_dir}")

    malformed = 0
    paths = sorted(tags_dir.glob("*.csv"), key=lambda item: item.name.casefold())
    for tag_position, path in enumerate(paths):
        tag_key = path.name[:-4]
        database.import_legacy_tag_definition(tag_key, tag_position)
        book_ids: list[int] = []
        seen: set[int] = set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            for row in reader:
                try:
                    book_id = int(row[0].strip())
                except (IndexError, ValueError):
                    malformed += 1
                    continue
                if book_id > 0 and book_id not in seen:
                    book_ids.append(book_id)
                    seen.add(book_id)
        if database.legacy_tag_membership_count(tag_key) != len(book_ids):
            database.import_legacy_tag_membership(tag_key, book_ids)

    stats = database.legacy_tag_snapshot_stats()
    stats["malformed_rows"] = malformed
    database.set_metadata("legacy_tag_snapshot_root", str(legacy_root.resolve()))
    database.set_metadata("legacy_tag_snapshot_memberships", str(stats["memberships"]))
    if database.get_metadata("legacy_import_completed_at") is None:
        row = database.connection.execute("SELECT MIN(fetched_at) FROM pages").fetchone()
        marker = row[0] if row and row[0] else datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        database.set_metadata("legacy_import_completed_at", str(marker))
    return stats


def export_updated_legacy_tags(
    database: Database,
    out_dir: Path,
    *,
    delta: float = 2.5,
) -> dict[str, int]:
    tag_keys = database.legacy_tag_keys()
    if not tag_keys:
        raise RuntimeError("尚未保存历史标签成员快照，请先运行 snapshot-legacy-tags")

    out_dir.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []
    total_books = 0
    refreshed_books: set[int] = set()
    baseline_marker = database.get_metadata("legacy_import_completed_at")

    for tag_key in tag_keys:
        rows = database.legacy_tag_books(tag_key)
        path = out_dir / f"{tag_key}.csv"
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TAG_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                item = dict(row)
                item["score"] = integrated_score(item.get("rating"), item.get("votes"), delta)
                writer.writerow(item)
                if baseline_marker is None or str(item["updated_at"]) > baseline_marker:
                    refreshed_books.add(int(item["douban_id"]))
        temp_path.replace(path)
        total_books += len(rows)
        index_rows.append({"tag": tag_key, "book_count": len(rows), "file": path.name})

    expected_files = {"Tags_info.csv", *(f"{tag_key}.csv" for tag_key in tag_keys)}
    for stale_path in out_dir.glob("*.csv"):
        if stale_path.name not in expected_files:
            stale_path.unlink()

    _write_index_csv(out_dir / "Tags_info.csv", index_rows)
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "membership_policy": "2020 historical tag membership and order; current database fields",
        "tags": len(tag_keys),
        "membership_rows": total_books,
        "distinct_books_refreshed_after_baseline": len(refreshed_books),
        "fallback": "Books not seen in the current crawl retain their legacy values.",
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    database.set_metadata("legacy_tag_export_completed_at", summary["generated_at"])
    return {"tags": len(tag_keys), "memberships": total_books, "refreshed_books": len(refreshed_books)}


def _write_index_csv(path: Path, rows: list[dict[str, object]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("tag", "book_count", "file"))
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)
