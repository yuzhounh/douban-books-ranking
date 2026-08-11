import sqlite3

from douban_books.models import BookListing, SourceSpec
from douban_books.storage import Database


def test_database_upsert_and_completed_page(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    with Database(db_path) as database:
        source_id = database.upsert_source(SourceSpec("tag", "测试"))
        book = BookListing(123, "测试书", 8.8, 456, "作者 / 出版社", "https://book.douban.com/subject/123/")
        database.save_page(
            source_id=source_id,
            url="https://book.douban.com/tag/test?start=0",
            next_url=None,
            books=[book],
            position_offset=0,
            http_status=200,
            cache_path=None,
        )

        page = database.completed_page(source_id, "https://book.douban.com/tag/test?start=0")
        assert page is not None
        assert page["item_count"] == 1
        assert database.stats()["books"] == 1

        database.save_page_error(source_id, "https://book.douban.com/tag/test?start=0", "refresh failed")
        assert database.completed_page(source_id, "https://book.douban.com/tag/test?start=0") is not None


def test_database_migrates_legacy_source_kind_constraint(tmp_path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('tag', 'doulist', 'series')),
            source_key TEXT NOT NULL,
            label TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(kind, source_key)
        )
        """
    )
    connection.execute("INSERT INTO sources(kind, source_key, label) VALUES ('tag', '文学', '文学')")
    connection.commit()
    connection.close()

    with Database(db_path) as database:
        top250_id = database.upsert_source(SourceSpec("top250", "top250"), "豆瓣读书 Top 250")
        assert top250_id > 0
        assert database.source_counts() == {"tag": 1, "top250": 1}
        assert not list(database.connection.execute("PRAGMA foreign_key_check"))


def test_prune_small_and_failed_sources(tmp_path) -> None:
    books = [
        BookListing(
            index,
            f"书 {index}",
            8.0,
            100,
            None,
            f"https://book.douban.com/subject/{index}/",
        )
        for index in range(1, 121)
    ]
    with Database(tmp_path / "prune.sqlite3") as database:
        database.import_legacy_books(books)
        for position, (tag, members) in enumerate(
            (("保留标签", books[:100]), ("低数量标签", books[:99]))
        ):
            database.import_legacy_tag_definition(tag, position)
            database.import_legacy_tag_membership(tag, [book.douban_id for book in members])
            source_id = database.upsert_source(SourceSpec("tag", tag), tag)
            database.import_legacy_links(members, source_id=source_id)

        keep_id = database.upsert_source(SourceSpec("doulist", "1"), "保留豆列")
        low_id = database.upsert_source(SourceSpec("doulist", "2"), "低数量豆列")
        failed_id = database.upsert_source(SourceSpec("doulist", "3"), "失败豆列")
        database.import_legacy_links(books[:10], source_id=keep_id)
        database.import_legacy_links(books[:9], source_id=low_id)
        database.import_legacy_links(books[:20], source_id=failed_id)
        database.save_page_error(failed_id, "https://www.douban.com/doulist/3/", "HTTP 403")

        removed = database.prune_small_and_failed_sources()

        assert removed["tags"] == ["低数量标签"]
        assert removed["doulists"] == ["2", "3"]
        assert removed["failed_doulists"] == ["3"]
        assert removed["small_doulists"] == ["2"]
        assert database.legacy_tag_keys() == ["保留标签"]
        assert database.source_counts() == {"doulist": 1, "tag": 1}
        assert not list(database.connection.execute("PRAGMA foreign_key_check"))
