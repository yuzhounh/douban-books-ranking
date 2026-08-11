from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from .models import BookListing, SourceSpec


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('top250', 'tag', 'doulist', 'series')),
    source_key TEXT NOT NULL,
    label TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kind, source_key)
);

CREATE TABLE IF NOT EXISTS books (
    douban_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    rating REAL,
    votes INTEGER,
    metadata TEXT,
    url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS book_sources (
    book_id INTEGER NOT NULL REFERENCES books(douban_id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(book_id, source_id)
);

CREATE TABLE IF NOT EXISTS pages (
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    next_url TEXT,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    http_status INTEGER,
    item_count INTEGER NOT NULL DEFAULT 0,
    cache_path TEXT,
    error TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(source_id, url)
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS legacy_tag_membership (
    tag_key TEXT NOT NULL,
    book_id INTEGER NOT NULL REFERENCES books(douban_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY(tag_key, book_id)
);

CREATE TABLE IF NOT EXISTS legacy_tag_definitions (
    tag_key TEXT PRIMARY KEY,
    position INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_books_rating_votes ON books(rating DESC, votes DESC);
CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(source_id, status);
CREATE INDEX IF NOT EXISTS idx_legacy_tag_position ON legacy_tag_membership(tag_key, position);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._migrate_source_kinds()

    def _migrate_source_kinds(self) -> None:
        """Expand legacy databases so Top 250 is a first-class source kind."""
        row = self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sources'"
        ).fetchone()
        if row is None or "'top250'" in str(row[0]):
            return

        self.connection.commit()
        self.connection.execute("PRAGMA foreign_keys = OFF")
        try:
            self.connection.executescript(
                """
                BEGIN IMMEDIATE;
                DROP TABLE IF EXISTS sources_new;
                CREATE TABLE sources_new (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('top250', 'tag', 'doulist', 'series')),
                    source_key TEXT NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(kind, source_key)
                );
                INSERT INTO sources_new(id, kind, source_key, label, created_at)
                SELECT id, kind, source_key, label, created_at FROM sources;
                DROP TABLE sources;
                ALTER TABLE sources_new RENAME TO sources;
                COMMIT;
                """
            )
            violations = list(self.connection.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(f"数据库来源类型迁移后外键校验失败: {violations[:3]}")
        finally:
            self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def upsert_source(self, source: SourceSpec, label: str | None = None) -> int:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sources(kind, source_key, label) VALUES (?, ?, ?)
                ON CONFLICT(kind, source_key) DO UPDATE SET
                    label = COALESCE(excluded.label, sources.label)
                """,
                (source.kind, source.key, label),
            )
            row = connection.execute(
                "SELECT id FROM sources WHERE kind = ? AND source_key = ?",
                (source.kind, source.key),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def update_source_label(self, source_id: int, label: str | None) -> None:
        if not label:
            return
        with self.transaction() as connection:
            connection.execute("UPDATE sources SET label = ? WHERE id = ?", (label, source_id))

    def completed_page(self, source_id: int, url: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM pages WHERE source_id = ? AND url = ? AND status = 'completed'",
            (source_id, url),
        ).fetchone()

    def save_page(
        self,
        *,
        source_id: int,
        url: str,
        next_url: str | None,
        books: Sequence[BookListing],
        position_offset: int,
        http_status: int,
        cache_path: str | None,
    ) -> None:
        with self.transaction() as connection:
            for index, book in enumerate(books):
                connection.execute(
                    """
                    INSERT INTO books(douban_id, title, rating, votes, metadata, url)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(douban_id) DO UPDATE SET
                        title = CASE
                            WHEN excluded.title NOT LIKE '豆瓣书籍 %' THEN excluded.title
                            ELSE books.title
                        END,
                        rating = COALESCE(excluded.rating, books.rating),
                        votes = COALESCE(excluded.votes, books.votes),
                        metadata = COALESCE(excluded.metadata, books.metadata),
                        url = excluded.url,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (book.douban_id, book.title, book.rating, book.votes, book.metadata, book.url),
                )
                connection.execute(
                    """
                    INSERT INTO book_sources(book_id, source_id, position)
                    VALUES (?, ?, ?)
                    ON CONFLICT(book_id, source_id) DO UPDATE SET
                        position = MIN(book_sources.position, excluded.position),
                        seen_at = CURRENT_TIMESTAMP
                    """,
                    (book.douban_id, source_id, position_offset + index),
                )
            connection.execute(
                """
                INSERT INTO pages(source_id, url, next_url, status, http_status, item_count, cache_path, error)
                VALUES (?, ?, ?, 'completed', ?, ?, ?, NULL)
                ON CONFLICT(source_id, url) DO UPDATE SET
                    next_url = excluded.next_url,
                    status = 'completed',
                    http_status = excluded.http_status,
                    item_count = excluded.item_count,
                    cache_path = excluded.cache_path,
                    error = NULL,
                    fetched_at = CURRENT_TIMESTAMP
                """,
                (source_id, url, next_url, http_status, len(books), cache_path),
            )

    def save_page_error(self, source_id: int, url: str, error: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO pages(source_id, url, status, error)
                VALUES (?, ?, 'failed', ?)
                ON CONFLICT(source_id, url) DO UPDATE SET
                    status = CASE
                        WHEN pages.status = 'completed' THEN 'completed'
                        ELSE 'failed'
                    END,
                    error = excluded.error,
                    fetched_at = CURRENT_TIMESTAMP
                """,
                (source_id, url, error),
            )

    def import_legacy_books(
        self,
        books: Sequence[BookListing],
        *,
        source_id: int | None = None,
    ) -> None:
        if not books:
            return
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO books(douban_id, title, rating, votes, metadata, url)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(douban_id) DO UPDATE SET
                    title = CASE
                        WHEN books.title LIKE '豆瓣书籍 %' THEN excluded.title
                        ELSE books.title
                    END,
                    rating = COALESCE(books.rating, excluded.rating),
                    votes = COALESCE(books.votes, excluded.votes),
                    metadata = COALESCE(books.metadata, excluded.metadata)
                """,
                [
                    (book.douban_id, book.title, book.rating, book.votes, book.metadata, book.url)
                    for book in books
                ],
            )
            if source_id is not None:
                connection.executemany(
                    """
                    INSERT INTO book_sources(book_id, source_id, position)
                    VALUES (?, ?, ?)
                    ON CONFLICT(book_id, source_id) DO UPDATE SET
                        position = MIN(book_sources.position, excluded.position)
                    """,
                    [(book.douban_id, source_id, index) for index, book in enumerate(books)],
                )

    def import_legacy_links(self, books: Sequence[BookListing], *, source_id: int) -> None:
        if not books:
            return
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO book_sources(book_id, source_id, position)
                VALUES (?, ?, ?)
                ON CONFLICT(book_id, source_id) DO UPDATE SET
                    position = MIN(book_sources.position, excluded.position)
                """,
                [(book.douban_id, source_id, index) for index, book in enumerate(books)],
            )

    def source_has_links(self, source_id: int) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM book_sources WHERE source_id = ? LIMIT 1", (source_id,)
        ).fetchone()
        return row is not None

    def set_metadata(self, key: str, value: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )

    def get_metadata(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def source_counts(self) -> dict[str, int]:
        rows = self.connection.execute("SELECT kind, COUNT(*) FROM sources GROUP BY kind").fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def import_legacy_tag_membership(self, tag_key: str, book_ids: Sequence[int]) -> None:
        if not book_ids:
            return
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO legacy_tag_membership(tag_key, book_id, position)
                VALUES (?, ?, ?)
                ON CONFLICT(tag_key, book_id) DO UPDATE SET
                    position = MIN(legacy_tag_membership.position, excluded.position)
                """,
                [(tag_key, book_id, position) for position, book_id in enumerate(book_ids)],
            )

    def import_legacy_tag_definition(self, tag_key: str, position: int) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO legacy_tag_definitions(tag_key, position) VALUES (?, ?)
                ON CONFLICT(tag_key) DO UPDATE SET position = excluded.position
                """,
                (tag_key, position),
            )

    def legacy_tag_membership_count(self, tag_key: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM legacy_tag_membership WHERE tag_key = ?", (tag_key,)
            ).fetchone()[0]
        )

    def legacy_tag_keys(self) -> list[str]:
        return [
            str(row[0])
            for row in self.connection.execute(
                "SELECT tag_key FROM legacy_tag_definitions ORDER BY position, tag_key COLLATE NOCASE"
            )
        ]

    def legacy_tag_books(self, tag_key: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT b.*, m.position
                FROM legacy_tag_membership m
                JOIN books b ON b.douban_id = m.book_id
                WHERE m.tag_key = ?
                ORDER BY m.position, b.douban_id
                """,
                (tag_key,),
            )
        )

    def legacy_tag_snapshot_stats(self) -> dict[str, int]:
        tags = self.connection.execute("SELECT COUNT(*) FROM legacy_tag_definitions").fetchone()[0]
        memberships = self.connection.execute("SELECT COUNT(*) FROM legacy_tag_membership").fetchone()[0]
        return {"tags": int(tags), "memberships": int(memberships)}

    def prune_small_and_failed_sources(
        self, *, min_tag_books: int = 100, min_doulist_books: int = 10
    ) -> dict[str, Any]:
        """Remove low-value tag/doulist sources and doulists with failed pages."""
        low_tags = [
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT d.tag_key
                FROM legacy_tag_definitions d
                LEFT JOIN legacy_tag_membership m ON m.tag_key = d.tag_key
                GROUP BY d.tag_key
                HAVING COUNT(m.book_id) < ?
                ORDER BY d.position, d.tag_key COLLATE NOCASE
                """,
                (min_tag_books,),
            )
        ]
        removed_doulists = list(
            self.connection.execute(
                """
                SELECT s.id, s.source_key,
                       (SELECT COUNT(*) FROM book_sources bs WHERE bs.source_id = s.id) AS books,
                       EXISTS(
                           SELECT 1 FROM pages p
                           WHERE p.source_id = s.id AND p.status = 'failed'
                       ) AS had_failure
                FROM sources s
                WHERE s.kind = 'doulist'
                  AND (
                      (SELECT COUNT(*) FROM book_sources bs WHERE bs.source_id = s.id) < ?
                      OR EXISTS(
                          SELECT 1 FROM pages p
                          WHERE p.source_id = s.id AND p.status = 'failed'
                      )
                  )
                ORDER BY CAST(s.source_key AS INTEGER), s.source_key
                """,
                (min_doulist_books,),
            )
        )

        with self.transaction() as connection:
            if low_tags:
                placeholders = ",".join("?" for _ in low_tags)
                connection.execute(
                    f"DELETE FROM legacy_tag_membership WHERE tag_key IN ({placeholders})", low_tags
                )
                connection.execute(
                    f"DELETE FROM legacy_tag_definitions WHERE tag_key IN ({placeholders})", low_tags
                )
                connection.execute(
                    f"DELETE FROM sources WHERE kind = 'tag' AND source_key IN ({placeholders})",
                    low_tags,
                )
            doulist_ids = [int(row["id"]) for row in removed_doulists]
            if doulist_ids:
                placeholders = ",".join("?" for _ in doulist_ids)
                connection.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", doulist_ids)

        return {
            "tags": low_tags,
            "doulists": [str(row["source_key"]) for row in removed_doulists],
            "failed_doulists": [
                str(row["source_key"]) for row in removed_doulists if int(row["had_failure"])
            ],
            "small_doulists": [
                str(row["source_key"])
                for row in removed_doulists
                if int(row["books"]) < min_doulist_books
            ],
        }

    def all_books(self, min_rating: float | None = None, min_votes: int | None = None) -> list[sqlite3.Row]:
        where: list[str] = []
        params: list[object] = []
        if min_rating is not None:
            where.append("b.rating >= ?")
            params.append(min_rating)
        if min_votes is not None:
            where.append("b.votes >= ?")
            params.append(min_votes)
        condition = " WHERE " + " AND ".join(where) if where else ""
        return list(
            self.connection.execute(
                f"""
                SELECT b.*,
                       COUNT(bs.source_id) AS source_count,
                       GROUP_CONCAT(s.kind || ':' || s.source_key, ' | ') AS sources
                FROM books b
                LEFT JOIN book_sources bs ON bs.book_id = b.douban_id
                LEFT JOIN sources s ON s.id = bs.source_id
                {condition}
                GROUP BY b.douban_id
                """,
                params,
            )
        )

    def stats(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for name, query in {
            "books": "SELECT COUNT(*) FROM books",
            "rated_books": "SELECT COUNT(*) FROM books WHERE rating IS NOT NULL",
            "sources": "SELECT COUNT(*) FROM sources",
            "completed_pages": "SELECT COUNT(*) FROM pages WHERE status = 'completed'",
            "failed_pages": "SELECT COUNT(*) FROM pages WHERE status = 'failed'",
        }.items():
            result[name] = int(self.connection.execute(query).fetchone()[0])
        return result
