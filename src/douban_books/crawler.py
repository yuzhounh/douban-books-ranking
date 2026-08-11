from __future__ import annotations

from urllib.parse import parse_qs, quote, urlparse

from .client import PoliteHttpClient
from .models import CrawlSummary, SourceSpec
from .parsers import parse_listing_page
from .storage import Database


def source_url(source: SourceSpec) -> str:
    if source.kind == "top250" and source.key == "top250":
        return "https://book.douban.com/top250?start=0"
    if source.kind == "tag":
        return f"https://book.douban.com/tag/{quote(source.key, safe='')}?start=0&type=T"
    if source.kind == "doulist" and source.key.isdigit():
        return f"https://www.douban.com/doulist/{source.key}/?start=0"
    if source.kind == "series" and source.key.isdigit():
        return f"https://book.douban.com/series/{source.key}?start=0"
    raise ValueError(f"无效来源: {source.display_name}")


class Crawler:
    def __init__(self, database: Database, client: PoliteHttpClient) -> None:
        self.database = database
        self.client = client

    def crawl(self, source: SourceSpec, *, max_pages: int | None = None, refresh: bool = False) -> CrawlSummary:
        source_id = self.database.upsert_source(source)
        url: str | None = source_url(source)
        visited: set[str] = set()
        pages = 0
        fetched_pages = 0
        skipped = 0
        books_seen = 0

        while url and url not in visited and (max_pages is None or fetched_pages < max_pages):
            visited.add(url)
            completed = None if refresh else self.database.completed_page(source_id, url)
            if completed is not None:
                skipped += 1
                pages += 1
                books_seen += int(completed["item_count"])
                url = completed["next_url"]
                continue

            try:
                response = self.client.fetch(url)
                result = parse_listing_page(response.html, response.final_url, source.kind)
                offset = _page_offset(url)
                self.database.save_page(
                    source_id=source_id,
                    url=url,
                    # Some unavailable or exhausted Douban lists still render a
                    # pagination link on an empty page.  The crawler already
                    # treats an empty result as the end of the source; persist
                    # that same decision so resume/completion checks agree.
                    next_url=result.next_url if result.books else None,
                    books=result.books,
                    position_offset=offset,
                    http_status=response.status_code,
                    cache_path=response.cache_path,
                )
                self.database.update_source_label(source_id, result.page_title)
            except Exception as exc:
                self.database.save_page_error(source_id, url, str(exc))
                raise

            pages += 1
            fetched_pages += 1
            books_seen += len(result.books)
            if not result.books:
                url = None
            else:
                url = result.next_url

        return CrawlSummary(source, pages, books_seen, skipped)


def _page_offset(url: str) -> int:
    try:
        return int(parse_qs(urlparse(url).query).get("start", [0])[0])
    except (TypeError, ValueError):
        return 0
