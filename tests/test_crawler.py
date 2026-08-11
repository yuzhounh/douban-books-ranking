from douban_books.client import FetchResult
from douban_books.crawler import Crawler, source_url
from douban_books.models import SourceSpec
from douban_books.storage import Database


class FakeClient:
    def __init__(self, html: str) -> None:
        self.html = html
        self.urls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.urls.append(url)
        return FetchResult(self.html, url, 200, None)


def test_max_pages_limits_new_requests_not_resumed_pages(tmp_path) -> None:
    source = SourceSpec("tag", "测试")
    first_url = source_url(source)
    second_url = "https://book.douban.com/tag/%E6%B5%8B%E8%AF%95?start=20&type=T"
    html = """
    <li class="subject-item"><h2>
      <a href="https://book.douban.com/subject/999/" title="续页书">续页书</a>
    </h2></li>
    """
    client = FakeClient(html)

    with Database(tmp_path / "resume.sqlite3") as database:
        source_id = database.upsert_source(source)
        database.save_page(
            source_id=source_id,
            url=first_url,
            next_url=second_url,
            books=[],
            position_offset=0,
            http_status=200,
            cache_path=None,
        )
        summary = Crawler(database, client).crawl(source, max_pages=1)

        assert client.urls == [second_url]
        assert summary.pages == 2
        assert summary.pages_skipped == 1
        assert database.stats()["books"] == 1


def test_empty_page_is_persisted_as_terminal_even_with_next_link(tmp_path) -> None:
    source = SourceSpec("doulist", "123")
    first_url = source_url(source)
    html = """
    <div class="paginator">
      <span class="next"><a href="?start=25">后页</a></span>
    </div>
    """
    client = FakeClient(html)

    with Database(tmp_path / "empty-terminal.sqlite3") as database:
        summary = Crawler(database, client).crawl(source)
        source_id = database.upsert_source(source)
        page = database.completed_page(source_id, first_url)

        assert summary.pages == 1
        assert page is not None
        assert page["item_count"] == 0
        assert page["next_url"] is None
