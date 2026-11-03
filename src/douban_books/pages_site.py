from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping

from .ranking import integrated_score
from .storage import Database
from .pages_shards import write_all_pages


SITE_TITLE = "豆瓣读书排行榜"
PAGE_SIZE = 100


def build_pages_site(
    database: Database,
    out_dir: Path,
    *,
    delta: float = 2.5,
    min_tag_books: int = 100,
    min_doulist_books: int = 10,
) -> dict[str, Any]:
    """Build a dependency-free static site suitable for a GitHub project page."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("assets", "data"):
        target = out_dir / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()

    categories: dict[str, list[dict[str, Any]]] = {
        "top250": [],
        "tag": [],
        "doulist": [],
        "series": [],
    }
    link_count = 0

    all_rows = _rank(
        database.connection.execute(
            "SELECT douban_id, title, rating, votes FROM books"
        ),
        delta,
    )
    all_books_payload = {
        "count": len(all_rows),
        "page_size": PAGE_SIZE,
        "books": [
            [
                int(row["douban_id"]),
                str(row["title"]),
                None if row["rating"] is None else float(row["rating"]),
                None if row["votes"] is None else int(row["votes"]),
            ]
            for row in all_rows
        ],
    }
    _write_json(out_dir / "data" / "all-books.json", all_books_payload)
    all_pages = write_all_pages(all_books_payload, out_dir / "data")

    for kind, source_key, label, rows in _iter_sources(database):
        if kind == "tag" and len(rows) < min_tag_books:
            continue
        if kind == "doulist" and len(rows) < min_doulist_books:
            continue
        ordered_rows = _rank(rows, delta)
        books = [_book_record(row) for row in ordered_rows]
        filename = _source_filename(kind, source_key)
        page_files: list[str] = []
        page_count = max(1, math.ceil(len(books) / PAGE_SIZE))
        for page_number in range(1, page_count + 1):
            page_filename = filename.replace(".json", f"-page-{page_number}.json")
            page_files.append(f"data/{page_filename}")
            start = (page_number - 1) * PAGE_SIZE
            payload = {
                "source": {"kind": kind, "key": source_key, "label": label},
                "page": page_number,
                "pages": page_count,
                "count": len(books),
                "books": books[start : start + PAGE_SIZE],
            }
            _write_json(out_dir / "data" / page_filename, payload)
        categories[kind].append(
            {
                "key": source_key,
                "label": label,
                "count": len(books),
                "order": "score",
                "page_size": PAGE_SIZE,
                "files": page_files,
            }
        )
        link_count += len(books)

    for kind in ("doulist", "series"):
        categories[kind].sort(
            key=lambda item: (-int(item["count"]), str(item["label"]).casefold(), str(item["key"]))
        )

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    catalog = {
        "title": SITE_TITLE,
        "generated_at": generated_at,
        "formula": f"(评分 - {delta:g}) × ln(评价人数)",
        "all_books": {
            "count": len(all_rows),
            "file": "data/all-books.json",
            "paged": all_pages,
            "page_size": PAGE_SIZE,
        },
        "categories": categories,
    }
    _write_json(out_dir / "data" / "catalog.json", catalog)
    (out_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8", newline="\n")
    (out_dir / "assets" / "style.css").write_text(
        STYLE_CSS + PAGINATION_CSS + FILTER_CSS, encoding="utf-8", newline="\n"
    )
    (out_dir / "assets" / "mobile.css").write_text(MOBILE_CSS, encoding="utf-8", newline="\n")
    (out_dir / "assets" / "app.js").write_text(APP_JS, encoding="utf-8", newline="\n")
    (out_dir / "assets" / "i18n.js").write_text(I18N_JS, encoding="utf-8", newline="\n")
    (out_dir / "assets" / "pages-data.js").write_text(PAGES_DATA_JS, encoding="utf-8", newline="\n")
    (out_dir / "assets" / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8", newline="\n")
    (out_dir / "assets" / "all-books-worker.js").write_text(
        ALL_BOOKS_WORKER_JS, encoding="utf-8", newline="\n"
    )
    workflow_dir = out_dir / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "pages.yml").write_text(PAGES_WORKFLOW, encoding="utf-8", newline="\n")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    (out_dir / ".gitignore").write_text(REPOSITORY_GITIGNORE, encoding="utf-8", newline="\n")
    (out_dir / "README.md").write_text(
        _site_readme(database, categories, generated_at, delta),
        encoding="utf-8",
        newline="\n",
    )
    database.set_metadata("pages_site_completed_at", generated_at)
    return {
        "generated_at": generated_at,
        "sources": sum(len(items) for items in categories.values()),
        "links": link_count,
        "top250": len(categories["top250"]),
        "tags": len(categories["tag"]),
        "doulists": len(categories["doulist"]),
        "series": len(categories["series"]),
    }


def _site_readme(
    database: Database,
    categories: Mapping[str, list[dict[str, Any]]],
    generated_at: str,
    delta: float,
) -> str:
    book_count = database.stats()["books"]
    top250_books = sum(int(item["count"]) for item in categories["top250"])
    generated_date = generated_at[:10]
    return f"""# 豆瓣读书综合排行榜

[![Code License: MIT](https://img.shields.io/badge/Code%20License-MIT-D4A017.svg)](LICENSE)

从豆瓣读书公开的 Top 250、标签、豆列与丛书列表页采集书籍信息，按豆瓣 subject ID 去重，并以评分和评价人数计算综合排名。

> 使用前请确认你的使用方式符合豆瓣网站条款与当地法律。本项目只处理公开列表页，不绕过验证码或访问控制；遇到风控提示时应停止请求。

## 在线排行榜

在线展示页面：<https://yuzhounh.github.io/douban-books-ranking/>

页面首先提供“全部书籍”全库搜索，可按书名、豆瓣 ID、最低评分和最低评价人数筛选；其后按“标签、豆列、丛书、Top 250”四类来源展示综合排行榜。各来源支持名称搜索和分页浏览，点击“豆瓣”可打开对应书籍页面。

## 数据快照

本仓库记录的数据快照生成于 **{generated_date}**。以下数量对应这一快照，不代表豆瓣当前完整书目：

- 去重书籍：**{book_count:,} 本**
- 标签：**{len(categories['tag']):,} 个**，仅保留不少于 100 本书的标签
- 豆列：**{len(categories['doulist']):,} 个**，排除历史抓取失败及少于 10 本书的豆列
- 丛书：**{len(categories['series']):,} 个**
- 豆瓣读书 Top 250：**{top250_books:,} 本**

豆列和丛书按所含书籍数量从多到少排列。每个来源内部均按综合评分降序排列。

## 综合评分

```text
综合评分 = (评分 - {delta:g}) × ln(评价人数)
```

其中 `ln` 是自然对数。公式同时考虑书籍评分和评价样本量，并通过对数降低超高评价人数的边际影响；无评分记录排在最后。对于有评分的记录，实现中评价人数缺失或不大于 0 时综合分记为 0，避免计算 `ln(0)`。

## 数据内容

每条书籍记录包含：

| 字段 | 含义 |
|---|---|
| `id` | 豆瓣书籍 subject ID |
| `title` | 书名 |
| `rating` | 豆瓣评分 |
| `rating_count` | 评价人数 |
| `url` | 豆瓣书籍页面链接 |

网站目录位于 `data/catalog.json`，来源及未筛选的全部书籍按100本分块，浏览器只读取当前页。设置全库文字、评分或评价人数条件时才读取保留的 `data/all-books.json`，在Web Worker中筛选；默认仍为全部书籍，排名和完整检索能力保持。页面缓存8块，过期下载中止，失败可重试。

## 项目结构

```text
.
├─ src/douban_books/    # 爬虫、解析器、存储、排名、分析及发布代码
├─ tests/               # 自动化测试与脱敏 HTML 夹具
├─ sources/             # 最终保留的标签、豆列和丛书来源清单
├─ analysis/            # 最终统计摘要与分析报告
├─ assets/              # 展示页面的 JavaScript 与 CSS
├─ data/                # 按来源和分页拆分的公开书籍数据
├─ index.html           # GitHub Pages 入口
└─ pyproject.toml       # Python 包与依赖配置
```

`sources/tags.txt`、`sources/doulists.txt` 和 `sources/series.txt` 是清理后的抓取入口：标签不少于 100 本，豆列不少于 10 本且排除了历史抓取失败项。Top 250 使用固定入口，无需单独的 ID 清单。

SQLite 工作数据库、HTML 缓存、运行日志和备份不进入仓库；网站实际展示的书籍记录已按来源保存在 `data/` 中。

## 安装与抓取

需要 Python 3.10 或更高版本：

```powershell
git clone https://github.com/yuzhounh/douban-books-ranking.git
cd douban-books-ranking
python -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install -e ".[dev]"

douban-books crawl `
  --tag-file sources/tags.txt `
  --doulist-file sources/doulists.txt `
  --series-file sources/series.txt `
  --top250
```

默认使用 `data/douban_books.sqlite3` 保存进度，成功页面可断点续爬。请控制请求频率；遇到 HTTP 403、418、验证码或异常请求提示时应停止。

## 分析与测试

```powershell
douban-books analyze --out-dir analysis --top 5000
python -m pytest
```

分析实现位于 `src/douban_books/analysis.py` 和 `ranking.py`。`analysis/summary.json` 提供机器可读统计，`analysis/report.md` 提供简要报告。

## 更新与发布

在主项目完成抓取后，使用已有书籍记录的工作数据库重新生成并发布。默认读取当前工作目录下的 `data/douban_books.sqlite3`；仓库中的静态 JSON 不会自动导入数据库，数据库不存在时会创建空库。

```powershell
python -m douban_books finalize
python -m douban_books publish-pages `
  --site-dir data/github-pages `
  --checkout-dir data/pages-repository `
  --repository https://github.com/yuzhounh/douban-books-ranking.git
```

发布命令会提交并推送到目标仓库的 `main` 分支；发布使用的 checkout 目录必须位于 `main` 分支，请先妥善保存其中的本地修改。上述命令只更新本仓库，不会修改 `yuzhounh.github.io` 仓库。

## 说明

- 数据来源于公开页面，仅供研究、数据分析和个人阅读参考。
- 评分、评价人数及榜单内容会随豆瓣页面变化，本站不是豆瓣官方产品。
- 项目不包含验证码破解、账号池、登录 Cookie 获取、代理轮换或其他风控规避功能。

## 相关项目

- [Douban-books-2020](https://github.com/yuzhounh/Douban-books-2020): 2020 年读书结果，现提供便于表格软件浏览的 UTF-8 BOM CSV。
- [Douban-books-crawler-2020](https://github.com/yuzhounh/Douban-books-crawler-2020): 对应 2020 年结果的 Python 采集与 MATLAB 整理代码。
- [Douban-books-2017](https://github.com/yuzhounh/Douban-books-2017): 2017 年读书结果快照，记录 129,193 本书。
- [Douban-books-results](https://github.com/yuzhounh/Douban-books-results): 更早的读书结果快照，记录 34,636 本书。
- [douban-movies-ranking](https://github.com/yuzhounh/douban-movies-ranking): 采用相同评分思路的影视姊妹项目，数据来源和内容与图书独立。

历史结果与当前项目的采集时间、来源和整理方式不同；上述链接用于了解项目演进，不表示当前代码依赖旧仓库。

## 许可证

代码采用 [MIT 许可证](LICENSE)。MIT 授权范围为代码；第三方数据的权利归原平台和权利人，具体说明见 [LICENSE 中的数据声明](LICENSE)。
"""


def _iter_sources(database: Database) -> Iterable[tuple[str, str, str, list[Mapping[str, Any]]]]:
    for source in database.connection.execute(
        """
        SELECT id, source_key, COALESCE(NULLIF(label, ''), '豆瓣读书 Top 250') AS display_label
        FROM sources
        WHERE kind = 'top250'
        ORDER BY id
        """
    ):
        rows = list(
            database.connection.execute(
                """
                SELECT b.*, bs.position
                FROM book_sources bs
                JOIN books b ON b.douban_id = bs.book_id
                WHERE bs.source_id = ?
                ORDER BY bs.position, b.douban_id
                """,
                (source["id"],),
            )
        )
        yield "top250", str(source["source_key"]), str(source["display_label"]), rows

    # Tags deliberately use the frozen 2020 membership, including its exact member set.
    for tag_key in database.legacy_tag_keys():
        yield "tag", tag_key, tag_key, database.legacy_tag_books(tag_key)

    for kind in ("doulist", "series"):
        sources = database.connection.execute(
            """
            SELECT id, source_key, COALESCE(NULLIF(label, ''), source_key) AS display_label
            FROM sources
            WHERE kind = ?
            ORDER BY id
            """,
            (kind,),
        )
        for source in sources:
            rows = list(
                database.connection.execute(
                    """
                    SELECT b.*, bs.position
                    FROM book_sources bs
                    JOIN books b ON b.douban_id = bs.book_id
                    WHERE bs.source_id = ?
                    ORDER BY bs.position, b.douban_id
                    """,
                    (source["id"],),
                )
            )
            yield kind, str(source["source_key"]), str(source["display_label"]), rows


def _rank(rows: Iterable[Mapping[str, Any]], delta: float) -> list[Mapping[str, Any]]:
    def key(row: Mapping[str, Any]) -> tuple[float, float, int, int]:
        rating = float(row["rating"]) if row["rating"] is not None else None
        votes = int(row["votes"]) if row["votes"] is not None else 0
        score = integrated_score(rating, votes, delta)
        return (
            score if score is not None else float("-inf"),
            rating if rating is not None else -1.0,
            votes,
            -int(row["douban_id"]),
        )

    return sorted(rows, key=key, reverse=True)


def _book_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["douban_id"]),
        "title": str(row["title"]),
        "rating": None if row["rating"] is None else float(row["rating"]),
        "rating_count": None if row["votes"] is None else int(row["votes"]),
        "url": str(row["url"]),
    }


def _source_filename(kind: str, source_key: str) -> str:
    digest = hashlib.sha1(f"{kind}\0{source_key}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}.json"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )



# Packaged templates are the canonical UI. Generated root files keep the same
# mobile controls and recovery behavior when rebuilding from a new data snapshot.
_TEMPLATES = Path(__file__).with_name("templates")


def _template(relative: str) -> str:
    return (_TEMPLATES / relative).read_text(encoding="utf-8")


INDEX_HTML = _template("index.html")
STYLE_CSS = _template("assets/style.css")
MOBILE_CSS = _template("assets/mobile.css")
PAGINATION_CSS = ""
FILTER_CSS = ""
APP_JS = _template("assets/app.js")
I18N_JS = _template("assets/i18n.js")
PAGES_DATA_JS = _template("assets/pages-data.js")
FAVICON_SVG = _template("assets/favicon.svg")
ALL_BOOKS_WORKER_JS = _template("assets/all-books-worker.js")
PAGES_WORKFLOW = _template(".github/workflows/pages.yml")
REPOSITORY_GITIGNORE = _template(".gitignore")
