import csv
import math

from douban_books.exporter import export_rows
from douban_books.ranking import integrated_score, rank_books


def test_integrated_score_and_order() -> None:
    assert integrated_score(9.0, 1000) == (9.0 - 2.5) * math.log(1000)
    assert integrated_score(8.0, 0) == 0.0
    assert integrated_score(None, 100) is None

    rows = [
        {"douban_id": 1, "rating": 8.0, "votes": 100},
        {"douban_id": 2, "rating": 9.0, "votes": 1000},
        {"douban_id": 3, "rating": None, "votes": None},
    ]
    assert [row["douban_id"] for row in rank_books(rows)] == [2, 1, 3]


def test_csv_round_trip_special_characters(tmp_path) -> None:
    title = 'A, "B" 😺 <C>'
    path = tmp_path / "books.csv"
    row = {
        "douban_id": 1,
        "title": title,
        "rating": 9.1,
        "votes": 123,
        "score": 1.0,
        "url": "https://book.douban.com/subject/1/",
    }
    export_rows([row], path, "csv")

    with path.open(encoding="utf-8-sig", newline="") as handle:
        loaded = next(csv.DictReader(handle))
    assert loaded["title"] == title

