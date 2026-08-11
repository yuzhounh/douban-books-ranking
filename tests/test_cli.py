import douban_books.cli as cli
from douban_books.client import BlockedError
from douban_books.cli import build_parser, main
from douban_books.crawler import source_url
from douban_books.models import CrawlSummary


def test_cli_parser_and_empty_stats(tmp_path, capsys) -> None:
    parser = build_parser()
    args = parser.parse_args(["crawl", "--tag", "文学", "--max-pages", "1"])
    assert args.tag == ["文学"]
    assert args.max_pages == 1

    top250_args = parser.parse_args(["crawl", "--top250"])
    assert top250_args.top250 is True
    assert source_url(cli._collect_sources(top250_args)[0]) == "https://book.douban.com/top250?start=0"

    database = tmp_path / "empty.sqlite3"
    assert main(["stats", "--db", str(database)]) == 0
    output = capsys.readouterr().out
    assert "去重书籍: 0" in output


def test_filter_seed_file_removes_only_selected_entries(tmp_path) -> None:
    seed = tmp_path / "tags.txt"
    seed.write_text("# 标签\n保留\n删除\n", encoding="utf-8")

    cli._filter_seed_file(seed, {"删除"})

    assert seed.read_text("utf-8") == "# 标签\n保留\n"


class FakePoliteHttpClient:
    def __init__(self, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        pass


def test_crawl_skips_isolated_doulist_403_and_continues(tmp_path, monkeypatch, capsys) -> None:
    calls: list[str] = []

    class FakeCrawler:
        def __init__(self, _database, _client) -> None:
            pass

        def crawl(self, source, **_kwargs):
            calls.append(source.key)
            if source.key == "11477":
                raise BlockedError(
                    "豆瓣返回 HTTP 403，已停止以避免加重风控",
                    status_code=403,
                    url=source_url(source),
                )
            return CrawlSummary(source, 1, 0, 0)

    monkeypatch.setattr(cli, "PoliteHttpClient", FakePoliteHttpClient)
    monkeypatch.setattr(cli, "Crawler", FakeCrawler)

    result = main(
        [
            "crawl",
            "--db",
            str(tmp_path / "crawl.sqlite3"),
            "--doulist",
            "11477",
            "--doulist",
            "12000",
        ]
    )

    assert result == 1
    assert calls == ["11477", "12000"]
    assert "跳过不可访问来源" in capsys.readouterr().err


def test_crawl_stops_after_three_consecutive_doulist_403s(tmp_path, monkeypatch, capsys) -> None:
    calls: list[str] = []

    class FakeCrawler:
        def __init__(self, _database, _client) -> None:
            pass

        def crawl(self, source, **_kwargs):
            calls.append(source.key)
            raise BlockedError(
                "豆瓣返回 HTTP 403，已停止以避免加重风控",
                status_code=403,
                url=source_url(source),
            )

    monkeypatch.setattr(cli, "PoliteHttpClient", FakePoliteHttpClient)
    monkeypatch.setattr(cli, "Crawler", FakeCrawler)

    result = main(
        [
            "crawl",
            "--db",
            str(tmp_path / "crawl.sqlite3"),
            "--doulist",
            "1",
            "--doulist",
            "2",
            "--doulist",
            "3",
            "--doulist",
            "4",
        ]
    )

    assert result == 2
    assert calls == ["1", "2", "3"]
    assert "判断为全局风控并停止" in capsys.readouterr().err


def test_crawl_does_not_skip_series_418(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class FakeCrawler:
        def __init__(self, _database, _client) -> None:
            pass

        def crawl(self, source, **_kwargs):
            calls.append(source.key)
            raise BlockedError(
                "豆瓣返回 HTTP 418，已停止以避免加重风控",
                status_code=418,
                url=source_url(source),
            )

    monkeypatch.setattr(cli, "PoliteHttpClient", FakePoliteHttpClient)
    monkeypatch.setattr(cli, "Crawler", FakeCrawler)

    result = main(
        [
            "crawl",
            "--db",
            str(tmp_path / "crawl.sqlite3"),
            "--series",
            "1",
            "--series",
            "2",
        ]
    )

    assert result == 2
    assert calls == ["1"]
