from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable


FIELDS = (
    "douban_id",
    "title",
    "rating",
    "votes",
    "score",
    "url",
    "metadata",
    "source_count",
    "sources",
    "first_seen_at",
    "updated_at",
)


def export_rows(rows: Iterable[dict[str, Any]], path: Path, file_format: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    if file_format == "csv":
        _write_csv(materialized, path)
    elif file_format == "jsonl":
        _write_jsonl(materialized, path)
    else:
        raise ValueError(f"不支持的导出格式: {file_format}")
    return len(materialized)


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    # utf-8-sig lets Excel/WPS detect Unicode. csv handles commas, quotes and newlines.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")

