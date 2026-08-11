from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BookListing:
    douban_id: int
    title: str
    rating: float | None
    votes: int | None
    metadata: str | None
    url: str


@dataclass(frozen=True, slots=True)
class ParseResult:
    books: tuple[BookListing, ...]
    next_url: str | None
    page_title: str | None = None


@dataclass(frozen=True, slots=True)
class SourceSpec:
    kind: str
    key: str

    @property
    def display_name(self) -> str:
        names = {"top250": "Top 250", "tag": "标签", "doulist": "豆列", "series": "丛书"}
        return f"{names.get(self.kind, self.kind)}:{self.key}"


@dataclass(frozen=True, slots=True)
class CrawlSummary:
    source: SourceSpec
    pages: int
    books_seen: int
    pages_skipped: int
