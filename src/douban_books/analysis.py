from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

from .exporter import export_rows
from .ranking import rank_books
from .storage import Database


def create_analysis(database: Database, out_dir: Path, *, top_n: int = 1000, delta: float = 2.5) -> dict:
    rows = rank_books(database.all_books(), delta)
    rated = [row for row in rows if row["rating"] is not None]
    ratings = [float(row["rating"]) for row in rated]
    votes = [int(row["votes"]) for row in rated if row["votes"] is not None]
    scores = [float(row["score"]) for row in rated if row["score"] is not None]

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "formula": f"(rating - {delta}) * ln(votes)",
        "books": len(rows),
        "rated_books": len(rated),
        "unrated_books": len(rows) - len(rated),
        "source_counts": database.source_counts(),
        "rating": {
            "mean": _round(statistics.fmean(ratings)) if ratings else None,
            "median": _round(statistics.median(ratings)) if ratings else None,
            "buckets": {
                "<6": sum(value < 6 for value in ratings),
                "6-6.9": sum(6 <= value < 7 for value in ratings),
                "7-7.9": sum(7 <= value < 8 for value in ratings),
                "8-8.9": sum(8 <= value < 9 for value in ratings),
                ">=9": sum(value >= 9 for value in ratings),
            },
        },
        "votes": {
            "median": statistics.median(votes) if votes else None,
            "buckets": {
                "0": sum(value == 0 for value in votes),
                "1-99": sum(1 <= value < 100 for value in votes),
                "100-999": sum(100 <= value < 1000 for value in votes),
                "1000-9999": sum(1000 <= value < 10000 for value in votes),
                ">=10000": sum(value >= 10000 for value in votes),
            },
        },
        "thresholds": {
            "rating>=9_and_votes>=1000": sum(
                float(row["rating"]) >= 9 and int(row["votes"] or 0) >= 1000 for row in rated
            ),
            "rating>=8.5": sum(float(row["rating"]) >= 8.5 for row in rated),
        },
        "score": {
            "median": _round(statistics.median(scores)) if scores else None,
            "p90": _round(_percentile(scores, 0.9)) if scores else None,
            "p99": _round(_percentile(scores, 0.99)) if scores else None,
        },
        "top_10": [
            {
                "douban_id": row["douban_id"],
                "title": row["title"],
                "rating": row["rating"],
                "votes": row["votes"],
                "score": _round(row["score"]),
            }
            for row in rows[:10]
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    export_rows(rows[:top_n], out_dir / "top_books.csv", "csv")
    (out_dir / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def _render_markdown(report: dict) -> str:
    top_lines = "\n".join(
        f"{index}. {item['title']}（{item['rating']} 分，{item['votes']} 人，综合分 {item['score']}，ID {item['douban_id']}）"
        for index, item in enumerate(report["top_10"], start=1)
    )
    sources = "，".join(f"{key} {value}" for key, value in report["source_counts"].items())
    return f"""# 豆瓣读书数据分析

生成时间：{report['generated_at']}

## 覆盖情况

- 去重书籍：{report['books']}
- 有评分书籍：{report['rated_books']}
- 无评分书籍：{report['unrated_books']}
- 来源：{sources}

## 分布摘要

- 评分均值：{report['rating']['mean']}
- 评分中位数：{report['rating']['median']}
- 评价人数中位数：{report['votes']['median']}
- 综合分中位数：{report['score']['median']}
- 综合分 P90 / P99：{report['score']['p90']} / {report['score']['p99']}
- 评分 ≥ 9 且评价人数 ≥ 1000：{report['thresholds']['rating>=9_and_votes>=1000']}
- 评分 ≥ 8.5：{report['thresholds']['rating>=8.5']}

## 综合评分前十

{top_lines}
"""


def _percentile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * proportion
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)
