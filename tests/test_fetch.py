from datetime import UTC, datetime
from pathlib import Path

import pytest

from gooddaynews.ingest import fetch
from gooddaynews.ingest.fetch import Article, clean_text, fill_body, parse_feed
from gooddaynews.ingest.sources import Source, load_sources

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = Source("Example", "example.org", "https://example.org/feed", "news", "IN", 4)


def test_parse_feed_keeps_recent_and_undated_items():
    raw = (FIXTURES / "sample_feed.xml").read_bytes()
    items = parse_feed(SOURCE, raw, since=datetime(2026, 10, 6, tzinfo=UTC))

    assert [a.url for a in items] == ["https://example.org/solar-coop", "https://example.org/undated"]
    assert items[0].published_at == datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
    assert items[1].published_at is None


def test_parse_feed_strips_html_from_summary():
    raw = (FIXTURES / "sample_feed.xml").read_bytes()
    first = parse_feed(SOURCE, raw, since=datetime(2026, 10, 6, tzinfo=UTC))[0]
    assert first.feed_summary == "A community solar co-op now powers 400 homes."


def test_parse_feed_rejects_unreadable_feed():
    with pytest.raises(ValueError):
        parse_feed(SOURCE, b"<html>not a feed", since=datetime(2026, 1, 1, tzinfo=UTC))


def test_clean_text_collapses_whitespace_and_entities():
    assert clean_text("<p>Tom &amp;   Jerry</p>\n<br>") == "Tom & Jerry"


class _Robots:
    def __init__(self, allowed):
        self._allowed = allowed

    def allowed(self, url):
        return self._allowed


def _article():
    return Article(SOURCE, "https://example.org/a", "Title", "", None)


def test_fill_body_respects_robots_txt(monkeypatch):
    monkeypatch.setattr(fetch, "http_get", lambda url: pytest.fail("must not download a disallowed page"))
    a = fill_body(_article(), _Robots(False))
    assert a.body is None and a.error == "blocked by robots.txt"


def test_fill_body_records_short_pages_as_errors(monkeypatch):
    monkeypatch.setattr(fetch, "http_get", lambda url: b"<html><body><p>Subscribe to read.</p></body></html>")
    a = fill_body(_article(), _Robots(True))
    assert a.body is None and "no article text" in a.error


def test_fill_body_records_network_errors(monkeypatch):
    def boom(url):
        raise TimeoutError("timed out")

    monkeypatch.setattr(fetch, "http_get", boom)
    a = fill_body(_article(), _Robots(True))
    assert a.error == "TimeoutError: timed out"


def test_source_registry_is_valid():
    sources = load_sources()
    assert sources, "at least one active source"
    assert len({s.domain for s in sources}) == len(sources), "domains must be unique"
