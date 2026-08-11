import csv
import json
from pathlib import Path

from douban_books.legacy_tag_export import export_updated_legacy_tags, snapshot_legacy_tags
from douban_books.models import BookListing
from douban_books.storage import Database


def test_snapshot_and_export_preserve_membership_but_use_current_fields(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    tags_dir = root / "Tags"
    tags_dir.mkdir(parents=True)
    (tags_dir / "文学.csv").write_text(
        "ID,Rating,Votes,Title\n00000123,8.0,10,旧书名\n00000456,7.0,20,另一本\n",
        encoding="utf-8-sig",
    )
    (tags_dir / "空标签.csv").write_text("ID,Rating,Votes,Title\n", encoding="utf-8-sig")
    database_path = tmp_path / "books.sqlite3"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "已删除标签.csv").write_text("stale", encoding="utf-8")
    with Database(database_path) as database:
        database.import_legacy_books(
            [
                BookListing(123, "新书名,含逗号", 9.2, 999, None, "https://book.douban.com/subject/123/"),
                BookListing(456, "另一本", 7.0, 20, None, "https://book.douban.com/subject/456/"),
                BookListing(789, "当前新增但不应导出", 9.9, 9999, None, "https://book.douban.com/subject/789/"),
            ]
        )
        snapshot = snapshot_legacy_tags(database, root)
        exported = export_updated_legacy_tags(database, out_dir)

    assert snapshot["tags"] == 2
    assert snapshot["memberships"] == 2
    assert exported["memberships"] == 2
    with (tmp_path / "out" / "文学.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["douban_id"] for row in rows] == ["123", "456"]
    assert rows[0]["title"] == "新书名,含逗号"
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["tags"] == 2
    assert not (out_dir / "已删除标签.csv").exists()
    with (tmp_path / "out" / "空标签.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert list(csv.DictReader(handle)) == []
