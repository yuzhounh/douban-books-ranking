from pathlib import Path

from douban_books.analysis import create_analysis
from douban_books.legacy import import_legacy_dataset
from douban_books.storage import Database


def test_legacy_import_recovers_unquoted_commas_and_writes_analysis(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    (root / "Tags").mkdir(parents=True)
    (root / "Doulists").mkdir()
    (root / "Books_1.csv").write_text(
        "ID,Rating,Votes,Title\n00000123,9.1,1000,书名,带逗号\n00000456,8.0,10,普通书\n00000789,0.0,0,暂无评分\n",
        encoding="utf-8-sig",
    )
    (root / "Tags" / "文学.csv").write_text(
        "ID,Rating,Votes,Title\n00000123,9.1,1000,书名,带逗号\n",
        encoding="utf-8-sig",
    )
    (root / "Doulists" / "Doulist_00000042.csv").write_text(
        "ID,Rating,Votes,Date,Title,Author,Publisher\n00000456,8.0,10,2020,普通书,作者,出版社\n",
        encoding="utf-8-sig",
    )
    (root / "Doulists_info.csv").write_text(
        "Doulist ID,Number of books,Doulist name\n00000042,1,豆列&amp;名称\n",
        encoding="utf-8-sig",
    )

    with Database(tmp_path / "books.sqlite3") as database:
        summary = import_legacy_dataset(database, root, seed_dir=tmp_path / "seeds")
        rows = database.all_books()
        assert summary.master_rows == 3
        assert summary.tags == 1
        assert summary.doulists == 1
        assert {row["title"] for row in rows} == {"书名,带逗号", "普通书", "暂无评分"}
        assert next(row for row in rows if row["douban_id"] == 789)["rating"] is None
        report = create_analysis(database, tmp_path / "analysis", top_n=2)

    assert report["books"] == 3
    assert (tmp_path / "analysis" / "report.md").exists()
    assert (tmp_path / "seeds" / "tags.txt").read_text(encoding="utf-8") == "文学\n"
