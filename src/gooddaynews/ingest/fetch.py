"""Fetcher agents: read each source's RSS feed and extract the full article text."""

import html
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import trafilatura

from gooddaynews.ingest.sources import Source
from gooddaynews.settings import get_settings

MIN_BODY_CHARS = 400
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Article:
    source: Source
    url: str
    title: str
    feed_summary: str
    published_at: datetime | None
    body: str | None = None
    error: str | None = None


def http_get(url: str) -> bytes:
    s = get_settings()
    req = urllib.request.Request(url, headers={"User-Agent": s.user_agent, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=s.fetch_timeout) as resp:
        return resp.read()


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()


def entry_datetime(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*t[:6], tzinfo=UTC) if t else None


def parse_feed(source: Source, raw: bytes, since: datetime) -> list[Article]:
    """Feed entries published after `since`. Entries without a date are kept."""
    feed = feedparser.parse(raw)
    if feed.bozo and not feed.entries:
        raise ValueError(f"unreadable feed: {feed.bozo_exception}")
    articles = []
    for e in feed.entries:
        url, title = e.get("link"), clean_text(e.get("title", ""))
        if not url or not title:
            continue
        published = entry_datetime(e)
        if published and published < since:
            continue
        articles.append(Article(source, url, title, clean_text(e.get("summary", ""))[:1000], published))
    return articles


class RobotsCache:
    """Checks robots.txt once per host, so we only fetch pages the site allows."""

    def __init__(self):
        self._parsers: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        host = urlparse(url)
        key = f"{host.scheme}://{host.netloc}"
        if key not in self._parsers:
            parser = RobotFileParser()
            try:
                parser.parse(http_get(f"{key}/robots.txt").decode("utf-8", "ignore").splitlines())
                self._parsers[key] = parser
            except Exception:
                self._parsers[key] = None  # no readable robots.txt: allowed
        parser = self._parsers[key]
        return parser is None or parser.can_fetch(get_settings().user_agent, url)


def extract_body(page: bytes, url: str) -> str | None:
    text = trafilatura.extract(
        page.decode("utf-8", "ignore"), url=url,
        include_comments=False, include_tables=False, favor_precision=True,
    )
    return text if text and len(text) >= MIN_BODY_CHARS else None


def fill_body(article: Article, robots: RobotsCache) -> Article:
    """Download and extract the article text. Failures are recorded, not raised."""
    try:
        if not robots.allowed(article.url):
            article.error = "blocked by robots.txt"
        else:
            article.body = extract_body(http_get(article.url), article.url)
            if article.body is None:
                article.error = "no article text found (paywall or non-article page)"
    except Exception as exc:
        article.error = f"{type(exc).__name__}: {exc}"[:300]
    return article


def fetch_bodies(articles: list[Article], workers: int = 8) -> list[Article]:
    robots = RobotsCache()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda a: fill_body(a, robots), articles))
