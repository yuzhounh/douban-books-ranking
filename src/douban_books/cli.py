from __future__ import annotations

import argparse
from datetime import datetime
import os
import sys
from pathlib import Path
from typing import Iterable

from .client import BlockedError, FetchError, PoliteHttpClient
from .analysis import create_analysis
from .crawler import Crawler, source_url
from .exporter import export_rows
from .models import SourceSpec
from .legacy import import_legacy_dataset
from .legacy_tag_export import export_updated_legacy_tags, snapshot_legacy_tags
from .pages_site import build_pages_site
from .pages_publish import DEFAULT_REPOSITORY, publish_pages
from .ranking import rank_books
from .storage import Database


MAX_CONSECUTIVE_INACCESSIBLE_SOURCES = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douban-books",
        description="从豆瓣 Top 250、标签、豆列、丛书列表页采集书籍信息；不提供单本书抓取。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl = subparsers.add_parser("crawl", help="抓取列表页并写入 SQLite")
    _add_db_argument(crawl)
    crawl.add_argument("--top250", action="store_true", help="抓取豆瓣读书 Top 250")
    crawl.add_argument("--tag", action="append", default=[], help="标签名，可重复")
    crawl.add_argument("--doulist", action="append", default=[], help="豆列 ID，可重复")
    crawl.add_argument("--series", action="append", default=[], help="丛书 ID，可重复")
    crawl.add_argument("--tag-file", action="append", type=Path, default=[], help="标签文件，每行一个")
    crawl.add_argument("--doulist-file", action="append", type=Path, default=[], help="豆列 ID 文件，每行一个")
    crawl.add_argument("--series-file", action="append", type=Path, default=[], help="丛书 ID 文件，每行一个")
    crawl.add_argument("--max-pages", type=_positive_int, help="每个来源最多抓取页数")
    crawl.add_argument("--refresh", action="store_true", help="重新抓取已完成页面")
    crawl.add_argument("--delay", type=_nonnegative_float, default=5.0, help="请求最小间隔秒数，默认 5")
    crawl.add_argument("--jitter", type=_nonnegative_float, default=2.0, help="额外随机间隔上限，默认 2")
    crawl.add_argument("--timeout", type=float, default=20.0, help="请求超时秒数")
    crawl.add_argument("--retries", type=_nonnegative_int, default=4, help="429/5xx/网络错误重试次数")
    crawl.add_argument("--cache-dir", type=Path, default=Path("data/cache"), help="HTML gzip 缓存目录")
    crawl.add_argument(
        "--user-agent",
        default=_default_user_agent(),
        help="固定 User-Agent；建议通过 DOUBAN_CRAWLER_CONTACT 配置联系方式",
    )

    export = subparsers.add_parser("export", help="按综合评分排序并导出")
    _add_db_argument(export)
    export.add_argument("--out", type=Path, required=True, help="输出 .csv 或 .jsonl")
    export.add_argument("--format", choices=("csv", "jsonl"), help="默认由输出扩展名判断")
    export.add_argument("--delta", type=float, default=2.5, help="公式中的基准分，默认 2.5")
    export.add_argument("--min-rating", type=float)
    export.add_argument("--min-votes", type=_nonnegative_int)
    export.add_argument("--limit", type=_positive_int)

    stats = subparsers.add_parser("stats", help="显示数据库统计")
    _add_db_argument(stats)

    legacy = subparsers.add_parser("import-legacy", help="导入 Douban-books-2020 旧数据作为覆盖基线")
    _add_db_argument(legacy)
    legacy.add_argument("--root", required=True, type=Path, help="Douban-books-2020 数据根目录")
    legacy.add_argument("--series-root", type=Path, help="旧 Douban-books-results 的 Series 目录")
    legacy.add_argument("--seed-dir", type=Path, default=Path("data/seeds"), help="生成增量抓取来源文件")

    analyze = subparsers.add_parser("analyze", help="生成统计报告和综合评分榜单")
    _add_db_argument(analyze)
    analyze.add_argument("--out-dir", type=Path, default=Path("data/analysis"))
    analyze.add_argument("--top", type=_positive_int, default=1000, help="榜单导出数量")
    analyze.add_argument("--delta", type=float, default=2.5)

    snapshot_tags = subparsers.add_parser(
        "snapshot-legacy-tags", help="保存旧标签文件的精确书籍成员与顺序"
    )
    _add_db_argument(snapshot_tags)
    snapshot_tags.add_argument("--root", required=True, type=Path, help="Douban-books-2020 数据根目录")

    export_tags = subparsers.add_parser(
        "export-legacy-tags", help="用最终书籍信息重建全部历史标签文件"
    )
    _add_db_argument(export_tags)
    export_tags.add_argument("--out-dir", type=Path, default=Path("data/updated_tags"))
    export_tags.add_argument("--delta", type=float, default=2.5)

    pages = subparsers.add_parser("build-pages", help="生成独立 GitHub Pages 静态网站")
    _add_db_argument(pages)
    pages.add_argument("--out-dir", type=Path, default=Path("data/github-pages"))
    pages.add_argument("--delta", type=float, default=2.5)

    prune = subparsers.add_parser("prune-sources", help="删除低数量标签、豆列和历史失败豆列")
    _add_db_argument(prune)
    prune.add_argument("--seed-dir", type=Path, default=Path("data/seeds"))
    prune.add_argument("--min-tag-books", type=_positive_int, default=100)
    prune.add_argument("--min-doulist-books", type=_positive_int, default=10)

    publish = subparsers.add_parser("publish-pages", help="将生成的网站发布到独立 GitHub 仓库")
    publish.add_argument("--site-dir", type=Path, default=Path("data/github-pages"))
    publish.add_argument("--checkout-dir", type=Path, default=Path("data/pages-repository"))
    publish.add_argument("--repository", default=DEFAULT_REPOSITORY)

    finalize = subparsers.add_parser("finalize", help="爬取完成后生成分析、历史标签文件和网站")
    _add_db_argument(finalize)
    finalize.add_argument("--analysis-dir", type=Path, default=Path("data/analysis"))
    finalize.add_argument("--tags-dir", type=Path, default=Path("data/updated_tags"))
    finalize.add_argument("--pages-dir", type=Path, default=Path("data/github-pages"))
    finalize.add_argument("--top", type=_positive_int, default=5000)
    finalize.add_argument("--delta", type=float, default=2.5)
    return parser


def _add_db_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/douban_books.sqlite3"),
        help="SQLite 数据库路径，默认 data/douban_books.sqlite3",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "crawl":
            return _crawl(args)
        if args.command == "export":
            return _export(args)
        if args.command == "stats":
            return _stats(args)
        if args.command == "import-legacy":
            return _import_legacy(args)
        if args.command == "analyze":
            return _analyze(args)
        if args.command == "snapshot-legacy-tags":
            return _snapshot_legacy_tags(args)
        if args.command == "export-legacy-tags":
            return _export_legacy_tags(args)
        if args.command == "build-pages":
            return _build_pages(args)
        if args.command == "prune-sources":
            return _prune_sources(args)
        if args.command == "publish-pages":
            return _publish_pages(args)
        if args.command == "finalize":
            return _finalize(args)
    except (ValueError, OSError, FetchError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    return 0


def _crawl(args: argparse.Namespace) -> int:
    sources = _collect_sources(args)
    if not sources:
        raise ValueError("至少指定 --top250、一个 --tag、--doulist、--series 或对应文件")

    with Database(args.db) as database, PoliteHttpClient(
        delay=args.delay,
        jitter=args.jitter,
        timeout=args.timeout,
        retries=args.retries,
        user_agent=args.user_agent,
        cache_dir=args.cache_dir,
    ) as client:
        crawler = Crawler(database, client)
        failures = 0
        consecutive_inaccessible = 0
        for index, source in enumerate(sources, start=1):
            print(f"[{index}/{len(sources)}] {source.display_name}")
            try:
                summary = crawler.crawl(source, max_pages=args.max_pages, refresh=args.refresh)
            except BlockedError as exc:
                if _is_inaccessible_list_source(source, exc):
                    failures += 1
                    consecutive_inaccessible += 1
                    print(f"  跳过不可访问来源: {exc}", file=sys.stderr)
                    if consecutive_inaccessible >= MAX_CONSECUTIVE_INACCESSIBLE_SOURCES:
                        raise BlockedError(
                            f"连续 {consecutive_inaccessible} 个豆列/丛书入口返回 HTTP 403，"
                            "判断为全局风控并停止",
                            status_code=403,
                            url=exc.url,
                        ) from exc
                    continue
                raise
            except Exception as exc:
                print(f"  失败: {exc}", file=sys.stderr)
                failures += 1
                consecutive_inaccessible = 0
                continue
            consecutive_inaccessible = 0
            print(
                f"  完成：遍历 {summary.pages} 页，见到 {summary.books_seen} 条书籍记录，"
                f"跳过已完成 {summary.pages_skipped} 页"
            )
    return 1 if failures else 0


def _is_inaccessible_list_source(source: SourceSpec, exc: BlockedError) -> bool:
    """Treat only an isolated first-page 403 as an inaccessible list source."""
    return (
        source.kind in {"doulist", "series"}
        and exc.status_code == 403
        and exc.url == source_url(source)
    )


def _export(args: argparse.Namespace) -> int:
    file_format = args.format or args.out.suffix.lower().lstrip(".")
    if file_format not in {"csv", "jsonl"}:
        raise ValueError("请用 --format csv/jsonl，或将输出扩展名设为 .csv/.jsonl")
    with Database(args.db) as database:
        rows = rank_books(database.all_books(args.min_rating, args.min_votes), args.delta)
    if args.limit is not None:
        rows = rows[: args.limit]
    count = export_rows(rows, args.out, file_format)
    print(f"已导出 {count} 本书到 {args.out}")
    return 0


def _stats(args: argparse.Namespace) -> int:
    with Database(args.db) as database:
        stats = database.stats()
    labels = {
        "books": "去重书籍",
        "rated_books": "有评分书籍",
        "sources": "来源",
        "completed_pages": "完成页面",
        "failed_pages": "失败页面",
    }
    for key, value in stats.items():
        print(f"{labels[key]}: {value}")
    return 0


def _import_legacy(args: argparse.Namespace) -> int:
    with Database(args.db) as database:
        summary = import_legacy_dataset(
            database,
            args.root,
            series_root=args.series_root,
            seed_dir=args.seed_dir,
        )
    print(
        f"旧数据导入完成：主表 {summary.master_rows} 行，当前去重 {summary.unique_books} 本；"
        f"标签 {summary.tags}，豆列 {summary.doulists}，丛书 {summary.series}；"
        f"来源关联 {summary.source_links} 条，异常行 {summary.malformed_rows}"
    )
    return 0


def _analyze(args: argparse.Namespace) -> int:
    with Database(args.db) as database:
        report = create_analysis(database, args.out_dir, top_n=args.top, delta=args.delta)
    print(
        f"分析完成：{report['books']} 本书，{report['rated_books']} 本有评分；"
        f"报告位于 {args.out_dir}"
    )
    return 0


def _snapshot_legacy_tags(args: argparse.Namespace) -> int:
    with Database(args.db) as database:
        stats = snapshot_legacy_tags(database, args.root)
    print(
        f"历史标签快照完成：{stats['tags']} 个标签，{stats['memberships']} 条成员关系，"
        f"异常行 {stats['malformed_rows']}"
    )
    return 0


def _export_legacy_tags(args: argparse.Namespace) -> int:
    with Database(args.db) as database:
        stats = export_updated_legacy_tags(database, args.out_dir, delta=args.delta)
    print(
        f"历史标签文件已更新：{stats['tags']} 个标签，{stats['memberships']} 行，"
        f"本轮刷新书籍 {stats['refreshed_books']} 本；输出 {args.out_dir}"
    )
    return 0


def _build_pages(args: argparse.Namespace) -> int:
    with Database(args.db) as database:
        stats = build_pages_site(database, args.out_dir, delta=args.delta)
    print(
        f"网站已生成：Top 250 {stats['top250']}，标签 {stats['tags']}，豆列 {stats['doulists']}，"
        f"丛书 {stats['series']}；输出 {args.out_dir}"
    )
    return 0


def _prune_sources(args: argparse.Namespace) -> int:
    with Database(args.db) as database:
        removed = database.prune_small_and_failed_sources(
            min_tag_books=args.min_tag_books,
            min_doulist_books=args.min_doulist_books,
        )
    _filter_seed_file(args.seed_dir / "tags.txt", set(removed["tags"]))
    _filter_seed_file(args.seed_dir / "doulists.txt", set(removed["doulists"]))
    print(
        f"来源清理完成：标签 {len(removed['tags'])} 个；豆列 {len(removed['doulists'])} 个，"
        f"其中历史失败 {len(removed['failed_doulists'])} 个、少于阈值 {len(removed['small_doulists'])} 个"
    )
    return 0


def _filter_seed_file(path: Path, removed: set[str]) -> None:
    if not path.exists() or not removed:
        return
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    kept = [line for line in lines if line.strip() not in removed]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")


def _publish_pages(args: argparse.Namespace) -> int:
    result = publish_pages(args.site_dir, args.checkout_dir, repository=args.repository)
    action = "已发布" if result.changed else "内容无变化"
    print(f"GitHub Pages {action}：{result.repository}；提交 {result.commit or '无'}")
    return 0


def _finalize(args: argparse.Namespace) -> int:
    with Database(args.db) as database:
        report = create_analysis(database, args.analysis_dir, top_n=args.top, delta=args.delta)
        tags = export_updated_legacy_tags(database, args.tags_dir, delta=args.delta)
        pages = build_pages_site(database, args.pages_dir, delta=args.delta)
        database.set_metadata("finalization_completed_at", datetime.now().astimezone().isoformat(timespec="seconds"))
    print(
        f"最终处理完成：{report['books']} 本书；{tags['tags']} 个历史标签文件，"
        f"{tags['memberships']} 条成员记录；网站 {pages['sources']} 个来源"
    )
    return 0


def _collect_sources(args: argparse.Namespace) -> list[SourceSpec]:
    values = {
        "top250": ["top250"] if args.top250 else [],
        "tag": list(args.tag) + list(_read_many(args.tag_file)),
        "doulist": list(args.doulist) + list(_read_many(args.doulist_file)),
        "series": list(args.series) + list(_read_many(args.series_file)),
    }
    result: list[SourceSpec] = []
    seen: set[tuple[str, str]] = set()
    for kind, entries in values.items():
        for value in entries:
            key = value.strip()
            if not key or (kind not in {"tag", "top250"} and not key.isdigit()):
                if key:
                    raise ValueError(f"{kind} ID 必须是数字: {key}")
                continue
            marker = (kind, key)
            if marker not in seen:
                result.append(SourceSpec(kind, key))
                seen.add(marker)
    return result


def _read_many(paths: Iterable[Path]) -> Iterable[str]:
    for path in paths:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                value = line.strip()
                if value and not value.startswith("#"):
                    yield value


def _default_user_agent() -> str:
    contact = os.environ.get("DOUBAN_CRAWLER_CONTACT", "configure-contact")
    return f"DoubanBooksCrawler/1.0 (public list pages; contact: {contact})"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("不能小于 0")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("不能小于 0")
    return parsed
