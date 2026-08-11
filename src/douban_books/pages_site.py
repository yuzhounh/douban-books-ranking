from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping

from .storage import Database


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
            "page_size": PAGE_SIZE,
        },
        "categories": categories,
    }
    _write_json(out_dir / "data" / "catalog.json", catalog)
    (out_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8", newline="\n")
    (out_dir / "assets" / "style.css").write_text(
        STYLE_CSS + PAGINATION_CSS + FILTER_CSS, encoding="utf-8", newline="\n"
    )
    (out_dir / "assets" / "app.js").write_text(APP_JS, encoding="utf-8", newline="\n")
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

从豆瓣读书公开的 Top 250、标签、豆列与丛书列表页采集书籍信息，按豆瓣 subject ID 去重，并以评分和评价人数计算综合排名。

> 使用前请确认你的使用方式符合豆瓣网站条款与当地法律。本项目只处理公开列表页，不绕过验证码或访问控制；遇到风控提示时应停止请求。

## 在线排行榜

在线展示页面：<https://yuzhounh.github.io/douban-books-ranking/>

页面首先提供“全部书籍”全库搜索，可按书名、豆瓣 ID、最低评分和最低评价人数筛选；其后按“标签、豆列、丛书、Top 250”四类来源展示综合排行榜。各来源支持名称搜索和分页浏览，点击“豆瓣”可打开对应书籍页面。

## 当前数据规模

最近一次生成于 **{generated_date}**：

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

其中 `ln` 是自然对数。公式同时考虑书籍评分和评价样本量，并通过对数降低超高评价人数的边际影响；无评分记录排在最后。

## 数据内容

每条书籍记录包含：

| 字段 | 含义 |
|---|---|
| `id` | 豆瓣书籍 subject ID |
| `title` | 书名 |
| `rating` | 豆瓣评分 |
| `rating_count` | 评价人数 |
| `url` | 豆瓣书籍页面链接 |

网站目录位于 `data/catalog.json`，各来源按每页 100 本拆分为独立 JSON 文件，浏览器只加载当前页面所需的数据。“全部书籍”首次打开时按需加载紧凑索引 `data/all-books.json`，并在 Web Worker 中执行全库搜索与阈值筛选，避免阻塞页面交互。

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

在主项目完成抓取后重新生成并发布：

```powershell
python -m douban_books finalize
python -m douban_books publish-pages `
  --site-dir data/github-pages `
  --checkout-dir data/pages-repository `
  --repository https://github.com/yuzhounh/douban-books-ranking.git
```

发布命令只更新本仓库，不会修改 `yuzhounh.github.io` 仓库。

## 说明

- 数据来源于公开页面，仅供研究、数据分析和个人阅读参考。
- 评分、评价人数及榜单内容会随豆瓣页面变化，本站不是豆瓣官方产品。
- 项目不包含验证码破解、账号池、登录 Cookie 获取、代理轮换或其他风控规避功能。
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
        rating = float(row["rating"]) if row["rating"] is not None else -1.0
        votes = int(row["votes"]) if row["votes"] is not None else 0
        score = (rating - delta) * math.log(votes) if rating >= 0 and votes > 0 else float("-inf")
        return score, rating, votes, -int(row["douban_id"])

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


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="浏览和筛选豆瓣读书公开列表中的全部书籍、标签、豆列、丛书与 Top 250 排行">
  <title>豆瓣读书排行榜</title>
  <link rel="stylesheet" href="assets/style.css">
  <style>[hidden]{display:none!important}</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <p class="eyebrow">DOUBAN BOOKS ARCHIVE</p>
      <h1>豆瓣读书排行榜</h1>
      <p class="lede">从标签、豆列、丛书与 Top 250 重新发现值得读的书。</p>
      <p class="formula" id="formula">综合评分加载中…</p>
    </div>
  </header>
  <main>
    <nav class="tabs" aria-label="来源类别">
      <button class="tab active" data-kind="all">全部书籍 <span id="all-count"></span></button>
      <button class="tab" data-kind="tag">标签 <span id="tag-count"></span></button>
      <button class="tab" data-kind="doulist">豆列 <span id="doulist-count"></span></button>
      <button class="tab" data-kind="series">丛书 <span id="series-count"></span></button>
      <button class="tab" data-kind="top250">Top 250 <span id="top250-count"></span></button>
    </nav>
    <section class="workspace">
      <aside class="source-panel">
        <div id="all-controls" class="all-controls">
          <label for="all-book-search">搜索全部书籍</label>
          <input id="all-book-search" type="search" placeholder="输入书名或豆瓣 ID" autocomplete="off">
        </div>
        <div id="source-controls" hidden>
          <div id="source-search-fields">
            <label id="source-search-label" for="source-search">查找来源</label>
            <input id="source-search" type="search" placeholder="输入来源名" autocomplete="off">
          </div>
          <div id="source-list" class="source-list" aria-live="polite"></div>
        </div>
      </aside>
      <section class="books-panel">
        <div class="books-head">
          <div><p class="section-label" id="kind-label">全部书籍</p><h2 id="source-title">全部书籍</h2></div>
          <div id="all-threshold-controls" class="threshold-controls">
            <label for="min-rating">最低评分
              <input id="min-rating" type="number" min="0" max="10" step="0.1" value="0.0">
            </label>
            <label for="min-votes">最低评价人数
              <input id="min-votes" type="number" min="0" step="1" value="0">
            </label>
            <div class="filter-actions">
              <button id="apply-all-filters" class="primary-action">应用筛选</button>
              <button id="reset-all-filters">重置</button>
            </div>
          </div>
        </div>
        <p id="status" class="status">正在加载全部书籍索引…</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>#</th><th>ID</th><th>书名</th><th>评分</th><th class="rating-count">评价人数</th><th>链接</th></tr></thead>
            <tbody id="book-rows"></tbody>
          </table>
        </div>
        <nav id="pagination" class="pagination" aria-label="书籍分页" hidden>
          <button id="first-page" aria-label="第一页">首页</button>
          <button id="previous-page" aria-label="上一页">上一页</button>
          <label>第 <input id="page-number" type="number" min="1" value="1"> 页</label>
          <span id="page-total">/ 1 页</span>
          <button id="go-page">跳转</button>
          <button id="next-page" aria-label="下一页">下一页</button>
          <button id="last-page" aria-label="最后一页">末页</button>
        </nav>
      </section>
    </section>
  </main>
  <footer>
    <span>数据来自豆瓣公开的标签筛选页、豆列、丛书与 Top 250 页面，仅供学习、研究与索引。评分及评价人数可能随时间变化。 <a href="https://github.com/yuzhounh/douban-books-ranking" target="_blank" rel="noopener">查看源代码</a></span>
    <span id="generated-at"></span>
  </footer>
  <script src="assets/app.js" defer></script>
</body>
</html>
"""


STYLE_CSS = r""":root{--ink:#14221b;--muted:#66736c;--paper:#f5f1e8;--card:#fffdf8;--line:#dcd6ca;--green:#176b4d;--green2:#0d4f39;--gold:#bd7f2f;--shadow:0 18px 50px rgba(30,44,36,.09)}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif}.hero{background:var(--green2);color:#fff;padding:64px 24px 58px;position:relative;overflow:hidden}.hero:after{content:"";position:absolute;width:420px;height:420px;border:1px solid rgba(255,255,255,.12);border-radius:50%;right:-120px;top:-230px;box-shadow:0 0 0 70px rgba(255,255,255,.025),0 0 0 140px rgba(255,255,255,.02)}.hero-inner{max-width:1240px;margin:auto;position:relative;z-index:1}.eyebrow,.section-label{font-size:12px;letter-spacing:.18em;font-weight:800;color:#b8dac9}.hero h1{font-family:Georgia,"Noto Serif SC","Songti SC",serif;font-size:clamp(42px,7vw,76px);line-height:1;margin:14px 0 18px;font-weight:700}.lede{font-size:20px;margin:0;color:#d9ebe2}.formula{display:inline-block;margin:28px 0 0;padding:9px 14px;border:1px solid rgba(255,255,255,.18);border-radius:99px;color:#cce3d8;font-size:13px}.tabs{max-width:1240px;margin:-23px auto 0;padding:0 24px;display:flex;gap:8px;position:relative;z-index:2}.tab{border:1px solid var(--line);background:var(--card);padding:14px 24px;border-radius:12px 12px 0 0;font-size:15px;font-weight:700;color:var(--muted);cursor:pointer}.tab.active{color:var(--green);border-bottom-color:var(--card);box-shadow:0 -8px 24px rgba(30,44,36,.05)}.tab span{font-weight:500;margin-left:4px}.workspace{max-width:1240px;margin:0 auto 54px;padding:0 24px;display:grid;grid-template-columns:290px minmax(0,1fr);min-height:620px}.source-panel,.books-panel{background:var(--card);border:1px solid var(--line);box-shadow:var(--shadow)}.source-panel{padding:24px 16px;border-radius:0 0 0 16px}.source-panel label,.book-search{display:block;color:var(--muted);font-size:12px;font-weight:700}.source-panel input,.book-search input{width:100%;margin-top:8px;border:1px solid var(--line);border-radius:9px;padding:11px 12px;background:#fff;font:inherit;outline:none}.source-panel input:focus,.book-search input:focus{border-color:var(--green);box-shadow:0 0 0 3px rgba(23,107,77,.1)}.source-list{margin-top:16px;max-height:1200px;overflow:auto}.source-item{display:flex;width:100%;justify-content:space-between;gap:10px;border:0;border-radius:8px;padding:10px;background:transparent;text-align:left;color:var(--ink);cursor:pointer}.source-item:hover{background:#f0ece3}.source-item.active{background:#e4efe9;color:var(--green2);font-weight:700}.source-item span:last-child{color:var(--muted);font-variant-numeric:tabular-nums}.books-panel{padding:28px;border-left:0;border-radius:0 16px 16px 0;min-width:0}.books-head{display:flex;align-items:end;justify-content:space-between;gap:24px;border-bottom:1px solid var(--line);padding-bottom:20px}.section-label{color:var(--green);margin:0 0 7px}.books-head h2{font-family:Georgia,"Noto Serif SC","Songti SC",serif;margin:0;font-size:30px}.book-search{width:220px}.status{color:var(--muted);font-size:14px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;color:var(--muted);font-size:12px;letter-spacing:.04em;padding:12px 10px;border-bottom:1px solid var(--line);white-space:nowrap}td{padding:13px 10px;border-bottom:1px solid #ece7de;vertical-align:top}td:nth-child(1),td:nth-child(2),td:nth-child(4),td:nth-child(5){font-variant-numeric:tabular-nums;white-space:nowrap}th.rating-count,td.rating-count{text-align:right}td:nth-child(3){min-width:240px;font-weight:600}a{color:var(--green);text-underline-offset:3px}.load-more{display:block;margin:22px auto 0;border:1px solid var(--green);color:var(--green);background:transparent;border-radius:9px;padding:10px 22px;font-weight:700;cursor:pointer}.load-more:hover{background:#e4efe9}footer{max-width:1240px;margin:auto;padding:0 24px 36px;display:flex;justify-content:space-between;color:var(--muted);font-size:12px}@media(max-width:800px){.hero{padding-top:46px}.tabs{overflow:auto}.tab{white-space:nowrap;padding:12px 18px}.workspace{grid-template-columns:1fr}.source-panel{border-radius:0;max-height:270px}.source-list{max-height:150px}.books-panel{border-left:1px solid var(--line);border-top:0;border-radius:0 0 16px 16px;padding:20px 14px}.books-head{align-items:stretch;flex-direction:column}.book-search{width:100%}.hero h1{font-size:44px}footer{gap:12px;flex-direction:column}}"""


PAGINATION_CSS = r""".pagination{align-items:center;display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin:24px 0 4px}.pagination button{background:transparent;border:1px solid var(--line);border-radius:8px;color:var(--green);cursor:pointer;font-weight:700;padding:9px 12px}.pagination button:hover:not(:disabled){background:#e4efe9;border-color:var(--green)}.pagination button:disabled{color:#a6aea9;cursor:not-allowed}.pagination label,.pagination span{color:var(--muted);font-size:13px}.pagination input{border:1px solid var(--line);border-radius:7px;font:inherit;padding:7px;text-align:center;width:64px}@media(max-width:600px){.pagination{justify-content:flex-start}.pagination button{padding:8px 10px}.pagination #first-page,.pagination #last-page{display:none}}"""


FILTER_CSS = r""".all-controls{display:grid;gap:10px}.all-controls label{margin-top:6px}.threshold-controls{align-items:end;display:flex;gap:10px}.threshold-controls label{color:var(--muted);font-size:12px;font-weight:700}.threshold-controls input{background:#fff;border:1px solid var(--line);border-radius:9px;display:block;font:inherit;margin-top:8px;outline:none;padding:9px 10px;width:92px}.threshold-controls label:nth-child(2) input{width:116px}.threshold-controls input:focus{border-color:var(--green);box-shadow:0 0 0 3px rgba(23,107,77,.1)}.filter-actions{display:flex;gap:8px}.filter-actions button{border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--green);cursor:pointer;font:inherit;font-weight:700;padding:9px 12px;white-space:nowrap}.filter-actions button:hover{background:#e4efe9;border-color:var(--green)}.filter-actions .primary-action{background:var(--green);border-color:var(--green);color:#fff}.filter-actions .primary-action:hover{background:var(--green2)}@media(max-width:1000px){.books-head{align-items:stretch;flex-direction:column}.threshold-controls{flex-wrap:wrap}}@media(max-width:600px){.threshold-controls{align-items:stretch;display:grid;grid-template-columns:1fr 1fr}.threshold-controls input,.threshold-controls label:nth-child(2) input{width:100%}.filter-actions{grid-column:1/-1}.filter-actions button{flex:1}}"""


APP_JS = r"""const PAGE_SIZE=100;const labels={tag:'标签',doulist:'豆列',series:'丛书'};let catalog=null,kind='tag',books=[],shown=0;const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));fetch('data/catalog.json').then(r=>{if(!r.ok)throw Error(r.status);return r.json()}).then(data=>{catalog=data;$('#formula').textContent='综合评分 = '+data.formula;$('#generated-at').textContent='数据更新：'+new Date(data.generated_at).toLocaleString('zh-CN');for(const k of Object.keys(labels))$('#'+k+'-count').textContent=data.categories[k].length;renderSources();}).catch(()=>$('#status').textContent='目录加载失败，请稍后重试。');document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');kind=b.dataset.kind;books=[];shown=0;$('#kind-label').textContent=labels[kind];$('#source-title').textContent='请选择一个来源';$('#source-search').value='';$('#book-search').value='';$('#book-rows').innerHTML='';$('#status').textContent='请选择左侧来源';$('#load-more').hidden=true;renderSources();}));$('#source-search').addEventListener('input',renderSources);$('#book-search').addEventListener('input',()=>{shown=0;renderBooks();});$('#load-more').addEventListener('click',()=>{shown+=PAGE_SIZE;renderBooks(false)});function renderSources(){if(!catalog)return;const q=$('#source-search').value.trim().toLowerCase();const list=catalog.categories[kind].filter(x=>(x.label+' '+x.key).toLowerCase().includes(q));$('#source-list').innerHTML='';for(const src of list){const b=document.createElement('button');b.className='source-item';b.innerHTML='<span>'+esc(src.label)+'</span><span>'+src.count.toLocaleString()+'</span>';b.addEventListener('click',()=>loadSource(src,b));$('#source-list').appendChild(b)}if(!list.length)$('#source-list').textContent='没有匹配的来源';}async function loadSource(src,button){document.querySelectorAll('.source-item').forEach(x=>x.classList.remove('active'));button.classList.add('active');$('#source-title').textContent=src.label;$('#status').textContent='正在加载…';$('#book-rows').innerHTML='';$('#load-more').hidden=true;try{const r=await fetch(src.file);if(!r.ok)throw Error(r.status);const data=await r.json();books=data.books;shown=0;$('#book-search').value='';renderBooks()}catch(e){$('#status').textContent='数据加载失败，请稍后重试。'}}function renderBooks(reset=true){const q=$('#book-search').value.trim().toLowerCase();const filtered=books.filter(b=>!q||b.title.toLowerCase().includes(q)||String(b.id).includes(q));if(reset)shown=PAGE_SIZE;const slice=filtered.slice(0,shown);$('#book-rows').innerHTML=slice.map((b,i)=>'<tr><td>'+(i+1)+'</td><td>'+b.id+'</td><td>'+esc(b.title)+'</td><td>'+(b.rating??'—')+'</td><td>'+(b.rating_count==null?'—':b.rating_count.toLocaleString())+'</td><td><a href="'+encodeURI(b.url)+'" target="_blank" rel="noopener">豆瓣</a></td></tr>').join('');$('#status').textContent='共 '+filtered.length.toLocaleString()+' 本，按综合评分排序';$('#load-more').hidden=shown>=filtered.length;}"""


# The paginated implementation supersedes the original single-file client above.
APP_JS = r"""const labels={all:'全部书籍',tag:'标签',doulist:'豆列',series:'丛书',top250:'Top 250'};
const sourcePrompts={tag:['查找标签','输入标签名'],doulist:['查找豆列','输入豆列名'],series:['查找丛书','输入丛书名']};
let catalog=null,kind='all',source=null,books=[],page=1,totalPages=1,resultCount=0,requestId=0,allWorker=null;
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

fetch('data/catalog.json')
  .then(response=>{if(!response.ok)throw Error(response.status);return response.json()})
  .then(data=>{
    catalog=data;
    $('#formula').textContent='综合评分 = '+data.formula;
    $('#generated-at').textContent='数据更新：'+new Date(data.generated_at).toLocaleString('zh-CN');
    $('#all-count').textContent=data.all_books.count.toLocaleString();
    for(const name of ['tag','doulist','series','top250'])$('#'+name+'-count').textContent=data.categories[name].length;
    activateKind('all');
  })
  .catch(()=>$('#status').textContent='目录加载失败，请稍后重试。');

document.querySelectorAll('.tab').forEach(button=>button.addEventListener('click',()=>activateKind(button.dataset.kind)));
$('#source-search').addEventListener('input',renderSources);
$('#apply-all-filters').addEventListener('click',()=>loadAllBooks(1));
$('#reset-all-filters').addEventListener('click',()=>{
  $('#all-book-search').value='';$('#min-rating').value='0.0';$('#min-votes').value='0';loadAllBooks(1);
});
for(const selector of ['#all-book-search','#min-rating','#min-votes']){
  $(selector).addEventListener('keydown',event=>{if(event.key==='Enter')loadAllBooks(1)});
}
$('#first-page').addEventListener('click',()=>loadPage(1));
$('#previous-page').addEventListener('click',()=>loadPage(page-1));
$('#next-page').addEventListener('click',()=>loadPage(page+1));
$('#last-page').addEventListener('click',()=>loadPage(totalPages));
$('#go-page').addEventListener('click',goToInputPage);
$('#page-number').addEventListener('keydown',event=>{if(event.key==='Enter')goToInputPage()});

function activateKind(nextKind){
  if(!catalog)return;
  kind=nextKind;source=null;books=[];page=1;totalPages=1;resultCount=0;requestId++;
  document.querySelectorAll('.tab').forEach(item=>item.classList.toggle('active',item.dataset.kind===kind));
  $('#kind-label').textContent=labels[kind];
  $('#book-rows').innerHTML='';
  $('#pagination').hidden=true;
  const isAll=kind==='all';
  $('#all-controls').hidden=!isAll;
  $('#all-threshold-controls').hidden=!isAll;
  $('#source-controls').hidden=isAll;
  if(isAll){
    $('#source-title').textContent='全部书籍';
    loadAllBooks(1);
    return;
  }
  const hasSourceSearch=kind!=='top250';
  $('#source-search-fields').hidden=!hasSourceSearch;
  if(hasSourceSearch){
    const [label,placeholder]=sourcePrompts[kind];
    $('#source-search-label').textContent=label;
    $('#source-search').placeholder=placeholder;
  }
  $('#source-search').value='';
  $('#source-title').textContent='请选择一个来源';
  $('#status').textContent='请选择左侧来源';
  renderSources();
  selectFirstSource();
}

function renderSources(){
  if(!catalog||kind==='all')return;
  const query=$('#source-search').value.trim().toLowerCase();
  const matches=catalog.categories[kind].filter(item=>(item.label+' '+item.key).toLowerCase().includes(query));
  const list=$('#source-list');
  list.innerHTML='';
  for(const item of matches){
    const button=document.createElement('button');
    button.className='source-item'+(source===item?' active':'');
    button.setAttribute('aria-pressed',source===item?'true':'false');
    button.innerHTML='<span>'+esc(item.label)+'</span><span>'+item.count.toLocaleString()+'</span>';
    button.addEventListener('click',()=>{
      source=item;
      document.querySelectorAll('.source-item').forEach(node=>{node.classList.remove('active');node.setAttribute('aria-pressed','false')});
      button.classList.add('active');button.setAttribute('aria-pressed','true');
      $('#source-title').textContent=item.label;
      loadSourcePage(1);
    });
    list.appendChild(button);
  }
  if(!matches.length)list.textContent='没有匹配的来源';
}

function selectFirstSource(){const first=$('#source-list .source-item');if(first)first.click()}

function ensureAllWorker(){
  if(allWorker)return allWorker;
  allWorker=new Worker('assets/all-books-worker.js');
  allWorker.onmessage=event=>{
    const data=event.data;
    if(data.requestId!==requestId||kind!=='all')return;
    if(data.error){$('#status').textContent='全部书籍索引加载失败，请稍后重试。';return}
    books=data.books.map(item=>({id:item[0],title:item[1],rating:item[2],rating_count:item[3],url:'https://book.douban.com/subject/'+item[0]+'/'}));
    page=data.page;totalPages=data.pages;resultCount=data.count;
    renderBookRows(catalog.all_books.page_size);
    $('#status').textContent='第 '+page+' / '+totalPages+' 页，本页 '+books.length+' 本，共 '+resultCount.toLocaleString()+' 本，按综合评分排序';
    updatePagination();
  };
  return allWorker;
}

function loadAllBooks(target){
  const rating=Math.max(0,Math.min(10,Number($('#min-rating').value)||0));
  const votes=Math.max(0,Math.floor(Number($('#min-votes').value)||0));
  $('#min-rating').value=rating.toFixed(1);$('#min-votes').value=String(votes);
  const currentRequest=++requestId;
  $('#status').textContent='正在筛选全部书籍，首次使用需要加载索引…';
  $('#book-rows').innerHTML='';$('#pagination').hidden=true;
  ensureAllWorker().postMessage({requestId:currentRequest,file:catalog.all_books.file,page:target,pageSize:catalog.all_books.page_size,query:$('#all-book-search').value.trim(),minRating:rating,minVotes:votes});
}

async function loadSourcePage(target){
  if(!source)return;
  totalPages=source.files.length;
  target=Math.max(1,Math.min(totalPages,Number(target)||1));
  const currentRequest=++requestId;
  $('#status').textContent='正在加载第 '+target+' 页…';
  $('#book-rows').innerHTML='';$('#pagination').hidden=true;
  try{
    const response=await fetch(source.files[target-1]);
    if(!response.ok)throw Error(response.status);
    const data=await response.json();
    if(currentRequest!==requestId||kind==='all')return;
    books=data.books;page=target;resultCount=source.count;
    renderBookRows(source.page_size);
    $('#status').textContent='第 '+page+' / '+totalPages+' 页，本页 '+books.length+' 本，共 '+source.count.toLocaleString()+' 本，按综合评分排序';
    updatePagination();
  }catch(error){if(currentRequest===requestId)$('#status').textContent='这一页加载失败，请稍后重试。'}
}

function renderBookRows(pageSize){
  const offset=(page-1)*pageSize;
  $('#book-rows').innerHTML=books.map((book,index)=>'<tr><td>'+(offset+index+1)+'</td><td>'+book.id+'</td><td>'+esc(book.title)+'</td><td>'+(book.rating==null?'—':Number(book.rating).toFixed(1))+'</td><td class="rating-count">'+(book.rating_count==null?'—':book.rating_count.toLocaleString())+'</td><td><a href="'+encodeURI(book.url)+'" target="_blank" rel="noopener">豆瓣</a></td></tr>').join('');
}

function updatePagination(){
  $('#pagination').hidden=totalPages<=1;
  $('#page-number').value=page;$('#page-number').max=totalPages;
  $('#page-total').textContent='/ '+totalPages+' 页';
  $('#first-page').disabled=page===1;$('#previous-page').disabled=page===1;
  $('#next-page').disabled=page===totalPages;$('#last-page').disabled=page===totalPages;
}

function loadPage(target){if(kind==='all')loadAllBooks(target);else loadSourcePage(target)}
function goToInputPage(){loadPage($('#page-number').value)}
"""


ALL_BOOKS_WORKER_JS = r"""let booksPromise=null,cacheKey='',matches=[];

async function loadBooks(file){
  if(!booksPromise){
    booksPromise=fetch(new URL('../'+file,self.location.href)).then(response=>{
      if(!response.ok)throw Error(response.status);
      return response.json();
    }).then(data=>data.books);
  }
  return booksPromise;
}

self.onmessage=async event=>{
  const {requestId,file,page,pageSize,query,minRating,minVotes}=event.data;
  try{
    const books=await loadBooks(file);
    const normalizedQuery=String(query||'').trim().toLocaleLowerCase('zh-CN');
    const key=JSON.stringify([normalizedQuery,minRating,minVotes]);
    if(key!==cacheKey){
      matches=[];
      for(let index=0;index<books.length;index++){
        const book=books[index],rating=book[2],votes=book[3]??0;
        const ratingMatches=minRating<=0?true:rating!==null&&rating>=minRating;
        const textMatches=!normalizedQuery||String(book[0]).includes(normalizedQuery)||String(book[1]).toLocaleLowerCase('zh-CN').includes(normalizedQuery);
        if(ratingMatches&&votes>=minVotes&&textMatches)matches.push(index);
      }
      cacheKey=key;
    }
    const pages=Math.max(1,Math.ceil(matches.length/pageSize));
    const selectedPage=Math.max(1,Math.min(pages,Number(page)||1));
    const start=(selectedPage-1)*pageSize;
    const result=matches.slice(start,start+pageSize).map(index=>books[index]);
    self.postMessage({requestId,page:selectedPage,pages,count:matches.length,books:result});
  }catch(error){self.postMessage({requestId,error:String(error)})}
};
"""


PAGES_WORKFLOW = """name: Deploy GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v4
        with:
          path: .
      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@v4
"""


REPOSITORY_GITIGNORE = """__pycache__/
*.py[cod]
.pytest_cache/
.venv/
*.sqlite3
*.sqlite3-shm
*.sqlite3-wal
cache/
logs/
backups/
"""
