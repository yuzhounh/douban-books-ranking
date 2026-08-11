import json
from pathlib import Path

from douban_books.models import BookListing, SourceSpec
from douban_books.pages_site import build_pages_site
from douban_books.storage import Database


def test_build_pages_site_separates_sources_and_preserves_tag_membership(tmp_path: Path) -> None:
    books = [
        BookListing(1, "高分 <书>", 9.0, 1000, None, "https://book.douban.com/subject/1/"),
        BookListing(2, "普通书", 7.0, 20, None, "https://book.douban.com/subject/2/"),
        BookListing(3, "标签外新书", 9.8, 9999, None, "https://book.douban.com/subject/3/"),
    ]
    with Database(tmp_path / "books.sqlite3") as database:
        database.import_legacy_books(books)
        database.import_legacy_tag_definition("文学/小说", 0)
        database.import_legacy_tag_membership("文学/小说", [2, 1])
        top250_id = database.upsert_source(SourceSpec("top250", "top250"), "豆瓣读书 Top 250")
        doulist_id = database.upsert_source(SourceSpec("doulist", "123"), "豆列名称")
        series_id = database.upsert_source(SourceSpec("series", "456"), "丛书名称")
        database.import_legacy_links([books[1], books[0]], source_id=top250_id)
        database.import_legacy_links(books, source_id=doulist_id)
        database.import_legacy_links(books[:2], source_id=series_id)

        stats = build_pages_site(
            database, tmp_path / "site", min_tag_books=1, min_doulist_books=1
        )

    catalog = json.loads((tmp_path / "site" / "data" / "catalog.json").read_text("utf-8"))
    index_html = (tmp_path / "site" / "index.html").read_text("utf-8")
    assert catalog["title"] == "豆瓣读书排行榜"
    assert "<title>豆瓣读书排行榜</title>" in index_html
    assert "<h1>豆瓣读书排行榜</h1>" in index_html
    assert 'id="all-threshold-controls"' in index_html
    assert index_html.index('id="all-threshold-controls"') > index_html.index('class="books-head"')
    assert "查找榜单" not in index_html
    assert stats == {
        "generated_at": stats["generated_at"],
        "sources": 4,
        "links": 9,
        "top250": 1,
        "tags": 1,
        "doulists": 1,
        "series": 1,
    }
    assert set(catalog["categories"]) == {"top250", "tag", "doulist", "series"}
    top250_source = catalog["categories"]["top250"][0]
    assert top250_source["order"] == "score"
    top250_payload = json.loads(
        (tmp_path / "site" / top250_source["files"][0]).read_text("utf-8")
    )
    assert [book["id"] for book in top250_payload["books"]] == [1, 2]
    tag_source = catalog["categories"]["tag"][0]
    assert tag_source["page_size"] == 100
    assert len(tag_source["files"]) == 1
    tag_file = tag_source["files"][0]
    tag_payload = json.loads((tmp_path / "site" / tag_file).read_text("utf-8"))
    assert [book["id"] for book in tag_payload["books"]] == [1, 2]
    assert set(tag_payload["books"][0]) == {"id", "title", "rating", "rating_count", "url"}
    assert 3 not in {book["id"] for book in tag_payload["books"]}
    assert (tmp_path / "site" / "index.html").exists()
    assert (tmp_path / "site" / "assets" / "app.js").exists()
    assert (tmp_path / "site" / "assets" / "all-books-worker.js").exists()
    assert (tmp_path / "site" / ".github" / "workflows" / "pages.yml").exists()
    readme = (tmp_path / "site" / "README.md").read_text("utf-8")
    assert readme.index("## 在线排行榜") < readme.index("## 当前数据规模")
    assert "https://yuzhounh.github.io/douban-books-ranking/" in readme[:1000]
    assert "### <https://yuzhounh.github.io" not in readme
    assert "src/douban_books/" in readme
    assert (tmp_path / "site" / ".gitignore").exists()
    style = (tmp_path / "site" / "assets" / "style.css").read_text("utf-8")
    assert ".source-list{margin-top:16px;max-height:1200px" in style
    assert "搜索全部书籍" in (tmp_path / "site" / "index.html").read_text("utf-8")


def test_build_pages_site_splits_large_sources_into_data_pages(tmp_path: Path) -> None:
    books = [
        BookListing(
            index,
            f"书籍 {index}",
            8.0,
            index + 10,
            None,
            f"https://book.douban.com/subject/{index}/",
        )
        for index in range(1, 206)
    ]
    with Database(tmp_path / "books.sqlite3") as database:
        database.import_legacy_books(books)
        database.import_legacy_tag_definition("大标签", 0)
        database.import_legacy_tag_membership("大标签", [book.douban_id for book in books])
        build_pages_site(database, tmp_path / "site")

    catalog = json.loads((tmp_path / "site" / "data" / "catalog.json").read_text("utf-8"))
    all_books = json.loads((tmp_path / "site" / catalog["all_books"]["file"]).read_text("utf-8"))
    assert catalog["all_books"]["count"] == 205
    assert len(all_books["books"]) == 205
    source = catalog["categories"]["tag"][0]
    assert source["count"] == 205
    assert source["page_size"] == 100
    assert len(source["files"]) == 3
    page_sizes = []
    for page_number, filename in enumerate(source["files"], start=1):
        payload = json.loads((tmp_path / "site" / filename).read_text("utf-8"))
        assert payload["page"] == page_number
        assert payload["pages"] == 3
        page_sizes.append(len(payload["books"]))
    assert page_sizes == [100, 100, 5]


def test_build_pages_site_filters_and_sorts_source_lists(tmp_path: Path) -> None:
    books = [
        BookListing(
            index,
            f"书籍 {index}",
            8.0,
            index + 10,
            None,
            f"https://book.douban.com/subject/{index}/",
        )
        for index in range(1, 121)
    ]
    with Database(tmp_path / "filters.sqlite3") as database:
        database.import_legacy_books(books)
        database.import_legacy_tag_definition("保留标签", 0)
        database.import_legacy_tag_membership("保留标签", [book.douban_id for book in books[:100]])
        database.import_legacy_tag_definition("低数量标签", 1)
        database.import_legacy_tag_membership("低数量标签", [book.douban_id for book in books[:99]])
        for key, count in (("10", 20), ("11", 9)):
            source_id = database.upsert_source(SourceSpec("doulist", key), f"豆列 {key}")
            database.import_legacy_links(books[:count], source_id=source_id)
        for key, count in (("20", 5), ("21", 15)):
            source_id = database.upsert_source(SourceSpec("series", key), f"丛书 {key}")
            database.import_legacy_links(books[:count], source_id=source_id)

        build_pages_site(database, tmp_path / "site")

    catalog = json.loads((tmp_path / "site" / "data" / "catalog.json").read_text("utf-8"))
    assert [item["label"] for item in catalog["categories"]["tag"]] == ["保留标签"]
    assert [item["key"] for item in catalog["categories"]["doulist"]] == ["10"]
    assert [item["key"] for item in catalog["categories"]["series"]] == ["21", "20"]
    assert catalog["formula"] == "(评分 - 2.5) × ln(评价人数)"
    index = (tmp_path / "site" / "index.html").read_text("utf-8")
    assert index.index('data-kind="all"') < index.index('data-kind="tag"')
    assert index.index('data-kind="tag"') < index.index('data-kind="top250"')
    assert "从标签、豆列、丛书与 Top 250 重新发现值得读的书。" in index
    assert "数据来自豆瓣公开的标签筛选页、豆列、丛书与 Top 250 页面" in index
    assert "评分及评价人数可能随时间变化" in index
    assert "https://github.com/yuzhounh/douban-books-ranking" in index
    assert 'id="generated-at"' in index
    assert 'id="book-search"' not in index
