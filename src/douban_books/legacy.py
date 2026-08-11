from __future__ import annotations

import csv
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import BookListing, SourceSpec
from .storage import Database
from .text import clean_text


_DOULIST_FILE_RE = re.compile(r"Doulist_(\d+)\.csv$", re.IGNORECASE)
_SERIES_FILE_RE = re.compile(r"Series_(\d+)\.txt$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LegacyImportSummary:
    master_rows: int
    unique_books: int
    tags: int
    doulists: int
    series: int
    source_links: int
    malformed_rows: int


def import_legacy_dataset(
    database: Database,
    root: Path,
    *,
    series_root: Path | None = None,
    seed_dir: Path | None = None,
) -> LegacyImportSummary:
    master_path = root / "Books_1.csv"
    tags_dir = root / "Tags"
    doulists_dir = root / "Doulists"
    for required in (master_path, tags_dir, doulists_dir):
        if not required.exists():
            raise FileNotFoundError(f"缺少旧数据文件或目录: {required}")

    malformed = 0
    master_marker = f"legacy_master_complete:{master_path.resolve()}"
    existing_master_rows = database.get_metadata(master_marker)
    master_rows = int(existing_master_rows) if existing_master_rows is not None else 0
    if existing_master_rows is None:
        for batch in _batched(_read_master(master_path), 5000):
            database.import_legacy_books(batch)
            master_rows += len(batch)
        database.set_metadata(master_marker, str(master_rows))

    doulist_labels = _read_doulist_labels(root / "Doulists_info.csv")
    tag_keys: list[str] = []
    doulist_keys: list[str] = []
    series_keys: list[str] = []
    links = 0

    for path in sorted(tags_dir.glob("*.csv"), key=lambda item: item.name.casefold()):
        tag = path.name[:-4]
        source_id = database.upsert_source(SourceSpec("tag", tag), tag)
        if database.source_has_links(source_id):
            tag_keys.append(tag)
            continue
        books, bad = _read_source_csv(path, title_start=3)
        malformed += bad
        database.import_legacy_links(books, source_id=source_id)
        links += len(books)
        tag_keys.append(tag)

    for path in sorted(doulists_dir.glob("*.csv"), key=lambda item: item.name.casefold()):
        match = _DOULIST_FILE_RE.match(path.name)
        if not match:
            malformed += 1
            continue
        key = str(int(match.group(1)))
        source_id = database.upsert_source(SourceSpec("doulist", key), doulist_labels.get(key))
        if database.source_has_links(source_id):
            doulist_keys.append(key)
            continue
        books, bad = _read_source_csv(path, title_start=None)
        malformed += bad
        database.import_legacy_links(books, source_id=source_id)
        links += len(books)
        doulist_keys.append(key)

    if series_root is not None and series_root.exists():
        for path in sorted(series_root.glob("*.txt"), key=lambda item: item.name.casefold()):
            match = _SERIES_FILE_RE.match(path.name)
            if not match:
                continue
            key = str(int(match.group(1)))
            source_id = database.upsert_source(SourceSpec("series", key))
            if database.source_has_links(source_id):
                series_keys.append(key)
                continue
            books, bad = _read_series_file(path)
            malformed += bad
            database.import_legacy_books(books, source_id=source_id)
            links += len(books)
            series_keys.append(key)

    stats = database.stats()
    database.set_metadata("legacy_root", str(root.resolve()))
    database.set_metadata("legacy_master_rows", str(master_rows))
    database.set_metadata("legacy_unique_books_after_import", str(stats["books"]))
    if database.get_metadata("legacy_import_completed_at") is None:
        database.set_metadata(
            "legacy_import_completed_at",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )
    if seed_dir is not None:
        _write_seeds(seed_dir, tag_keys, doulist_keys, series_keys)

    return LegacyImportSummary(
        master_rows=master_rows,
        unique_books=stats["books"],
        tags=len(tag_keys),
        doulists=len(doulist_keys),
        series=len(series_keys),
        source_links=links,
        malformed_rows=malformed,
    )


def _read_master(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            book = _book_from_row(row, title_start=3)
            if book is not None:
                yield book


def _read_source_csv(path: Path, title_start: int | None) -> tuple[list[BookListing], int]:
    books: list[BookListing] = []
    malformed = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            book = _book_from_row(row, title_start=title_start)
            if book is None:
                malformed += 1
            else:
                books.append(book)
    return books, malformed


def _read_series_file(path: Path) -> tuple[list[BookListing], int]:
    books: list[BookListing] = []
    malformed = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, skipinitialspace=True)
        for row in reader:
            if len(row) < 5 or not row[0].strip().isdigit():
                continue
            # Old series format: ID, integrated score, rating, votes, title...
            shifted = [row[0], row[2], row[3], *row[4:]]
            book = _book_from_row(shifted, title_start=3)
            if book is None:
                malformed += 1
            else:
                books.append(book)
    return books, malformed


def _book_from_row(row: list[str], title_start: int | None) -> BookListing | None:
    if len(row) < 3:
        return None
    try:
        douban_id = int(row[0].strip())
        rating = float(row[1].strip()) if row[1].strip() else None
        votes = int(row[2].strip()) if row[2].strip() else None
    except ValueError:
        return None
    if douban_id <= 0:
        return None
    # The legacy crawler encoded "暂无评分" as 0.0; it is missing data, not a real score.
    if rating is not None and not 0.0 < rating <= 10.0:
        rating = None
    if votes is not None and votes < 0:
        votes = None
    title = ""
    if title_start is not None and len(row) > title_start:
        title = clean_text(",".join(row[title_start:]))
    if not title:
        title = f"豆瓣书籍 {douban_id}"
    return BookListing(
        douban_id=douban_id,
        title=title,
        rating=rating,
        votes=votes,
        metadata=None,
        url=f"https://book.douban.com/subject/{douban_id}/",
    )


def _read_doulist_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            if len(row) >= 3 and row[0].strip().isdigit():
                key = str(int(row[0].strip()))
                result[key] = clean_text(html.unescape(",".join(row[2:])))
    return result


def _batched(items, size: int):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _write_seeds(seed_dir: Path, tags: list[str], doulists: list[str], series: list[str]) -> None:
    seed_dir.mkdir(parents=True, exist_ok=True)
    for name, values in (("tags.txt", tags), ("doulists.txt", doulists), ("series.txt", series)):
        content = "\n".join(values) + ("\n" if values else "")
        (seed_dir / name).write_text(content, encoding="utf-8")
