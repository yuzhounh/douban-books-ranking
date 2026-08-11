from __future__ import annotations

import gzip
import hashlib
import random
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .parsers import looks_blocked


class FetchError(RuntimeError):
    pass


class BlockedError(FetchError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class RobotsDeniedError(FetchError):
    pass


@dataclass(frozen=True, slots=True)
class FetchResult:
    html: str
    final_url: str
    status_code: int
    cache_path: str | None


class PoliteHttpClient:
    """Serial HTTP client with robots checks, pacing, retry/backoff and gzip cache."""

    def __init__(
        self,
        *,
        delay: float = 5.0,
        jitter: float = 2.0,
        timeout: float = 20.0,
        retries: int = 4,
        user_agent: str = "DoubanBooksCrawler/1.0 (public list pages; configure contact)",
        cache_dir: Path | None = None,
    ) -> None:
        if delay < 0 or jitter < 0 or timeout <= 0 or retries < 0:
            raise ValueError("HTTP 参数不能为负数，timeout 必须大于 0")
        self.delay = delay
        self.jitter = jitter
        self.retries = retries
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self._last_request_at = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            },
            timeout=timeout,
            follow_redirects=True,
            trust_env=True,
        )

    def __enter__(self) -> "PoliteHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch(self, url: str) -> FetchResult:
        self._validate_url(url)
        if not self._robots_allowed(url):
            raise RobotsDeniedError(f"robots.txt 不允许抓取: {url}")

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._pace()
            try:
                response = self._client.get(url)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(self._backoff_seconds(attempt, None))
                continue

            final_url = str(response.url)
            if response.status_code in {403, 418}:
                raise BlockedError(
                    f"豆瓣返回 HTTP {response.status_code}，已停止以避免加重风控",
                    status_code=response.status_code,
                    url=url,
                )
            if response.status_code == 429 or response.status_code >= 500:
                last_error = FetchError(f"HTTP {response.status_code}: {url}")
                if attempt >= self.retries:
                    break
                time.sleep(self._backoff_seconds(attempt, response.headers.get("Retry-After")))
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise FetchError(str(exc)) from exc

            html = response.text
            if looks_blocked(html, final_url):
                raise BlockedError(
                    "检测到验证码或异常请求提示页，已保存进度并停止",
                    status_code=response.status_code,
                    url=url,
                )
            cache_path = self._write_cache(url, html)
            return FetchResult(html, final_url, response.status_code, cache_path)

        raise FetchError(f"请求重试耗尽: {url}; {last_error}") from last_error

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            parser: urllib.robotparser.RobotFileParser | None = None
            try:
                self._pace()
                response = self._client.get(robots_url)
                if response.status_code == 200 and "text" in response.headers.get("content-type", "text/plain"):
                    parser = urllib.robotparser.RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse(response.text.splitlines())
            except httpx.HTTPError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def _pace(self) -> None:
        target = self.delay + random.uniform(0.0, self.jitter)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < target:
            time.sleep(target - elapsed)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _backoff_seconds(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(300.0, max(0.0, float(retry_after)))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    now = datetime.now(timezone.utc)
                    return min(300.0, max(0.0, (retry_at - now).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(60.0, (2**attempt) + random.uniform(0.0, 1.0))

    def _write_cache(self, url: str, html: str) -> str | None:
        if self.cache_dir is None:
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".html.gz"
        path = self.cache_dir / name
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(temp_path, "wt", encoding="utf-8", newline="") as handle:
            handle.write(html)
        temp_path.replace(path)
        return str(path)

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"book.douban.com", "www.douban.com"}:
            raise FetchError(f"拒绝访问非豆瓣 HTTPS 地址: {url}")
