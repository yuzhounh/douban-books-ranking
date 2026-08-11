from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .models import BookListing, ParseResult
from .text import clean_text


_SUBJECT_RE = re.compile(r"https?://book\.douban\.com/subject/(\d+)/?")
_VOTES_RE = re.compile(r"([\d,，]+)\s*人评价")
_ALLOWED_HOSTS = {"book.douban.com", "www.douban.com"}
_ALLOWED_PATHS = ("/top250", "/tag/", "/series/", "/doulist/")


class ParseError(RuntimeError):
    pass


def looks_blocked(html: str, final_url: str = "") -> bool:
    sample = html[:100_000].lower()
    markers = (
        "检测到有异常请求",
        "sec.douban.com",
        "captcha",
        "请输入验证码",
        "访问豆瓣的方式有点异常",
    )
    return any(marker.lower() in sample for marker in markers) or "sec.douban.com" in final_url


def parse_listing_page(html: str, page_url: str, source_kind: str) -> ParseResult:
    if looks_blocked(html, page_url):
        raise ParseError("页面疑似为验证码或异常请求提示页")

    soup = BeautifulSoup(html, "html.parser")
    if source_kind == "top250":
        containers = soup.select("tr.item")
    elif source_kind == "doulist":
        containers = soup.select("div.doulist-item")
    elif source_kind in {"tag", "series"}:
        containers = soup.select("li.subject-item, div.subject-item")
    else:
        raise ValueError(f"不支持的来源类型: {source_kind}")

    books: list[BookListing] = []
    seen_ids: set[int] = set()
    for container in containers:
        book = _parse_book(container, source_kind)
        if book is None or book.douban_id in seen_ids:
            continue
        seen_ids.add(book.douban_id)
        books.append(book)

    title_node = soup.select_one("h1") or soup.select_one("title")
    page_title = clean_text(title_node.get_text(" ", strip=True)) if title_node else None
    return ParseResult(
        books=tuple(books),
        next_url=_find_next_url(soup, page_url),
        page_title=page_title or None,
    )


def _parse_book(container: Tag, source_kind: str) -> BookListing | None:
    link = _find_subject_link(container, source_kind)
    if link is None:
        return None
    match = _SUBJECT_RE.search(str(link.get("href", "")))
    if not match:
        return None

    douban_id = int(match.group(1))
    canonical_url = f"https://book.douban.com/subject/{douban_id}/"
    title = clean_text(str(link.get("title") or link.get_text(" ", strip=True)))
    if not title:
        title = f"豆瓣书籍 {douban_id}"

    rating_node = container.select_one(".rating_nums")
    rating = _to_float(rating_node.get_text(strip=True)) if rating_node else None

    votes = None
    rating_area = container.select_one(".rating, .star")
    if rating_area:
        vote_match = _VOTES_RE.search(rating_area.get_text(" ", strip=True))
        if vote_match:
            votes = int(vote_match.group(1).replace(",", "").replace("，", ""))

    metadata_selector = {
        "doulist": ".abstract",
        "top250": "p.pl",
    }.get(source_kind, ".pub")
    metadata_node = container.select_one(metadata_selector)
    metadata = clean_text(metadata_node.get_text(" / ", strip=True)) if metadata_node else ""
    return BookListing(
        douban_id=douban_id,
        title=title,
        rating=rating,
        votes=votes,
        metadata=metadata or None,
        url=canonical_url,
    )


def _find_subject_link(container: Tag, source_kind: str) -> Tag | None:
    if source_kind == "doulist":
        selectors = (
            ".title a[href*='book.douban.com/subject/']",
            "h2 a[href*='book.douban.com/subject/']",
        )
    elif source_kind == "top250":
        selectors = (".pl2 a[href*='book.douban.com/subject/']",)
    else:
        selectors = ("h2 a[href*='book.douban.com/subject/']", "a[href*='book.douban.com/subject/']")
    for selector in selectors:
        link = container.select_one(selector)
        if link and _SUBJECT_RE.search(str(link.get("href", ""))):
            return link
    return None


def _find_next_url(soup: BeautifulSoup, page_url: str) -> str | None:
    node = soup.select_one("span.next a[href], .paginator .next a[href], a.next[href], link[rel~='next'][href]")
    if not node:
        return None
    next_url = urljoin(page_url, str(node.get("href", "")))
    parsed = urlparse(next_url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        return None
    if not parsed.path.startswith(_ALLOWED_PATHS):
        return None
    return next_url


def _to_float(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0.0 <= result <= 10.0 else None
