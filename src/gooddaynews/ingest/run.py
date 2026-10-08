"""Run the fetcher agents.

    python -m gooddaynews.ingest.run --check-feeds          # test every feed, no article downloads
    python -m gooddaynews.ingest.run --dry-run --limit 3    # fetch a few articles, print, save nothing
    python -m gooddaynews.ingest.run                         # fetch and save new articles to the database
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta

from gooddaynews.ingest.fetch import Article, fetch_bodies, http_get, parse_feed
from gooddaynews.ingest.sources import FETCHERS, Source, load_sources, sync_sources
from gooddaynews.settings import get_settings


def read_feeds(sources: list[Source], since: datetime, limit: int | None) -> tuple[list[Article], dict]:
    """Read every feed. Returns the new feed items and a per-source error map."""
    items, errors = [], {}
    for s in sources:
        try:
            found = parse_feed(s, http_get(s.feed_url), since)
            items.extend(found[:limit] if limit else found)
            print(f"  {s.fetcher:<9} {s.name:<28} {len(found):>3} recent items")
        except Exception as exc:
            errors[s.domain] = f"{type(exc).__name__}: {exc}"[:300]
            print(f"  {s.fetcher:<9} {s.name:<28} FAILED  {errors[s.domain]}")
    return items, errors


def save(conn, articles: list[Article]) -> Counter:
    counts = Counter()
    for a in articles:
        status = "new" if a.body else "error"
        rows = conn.run(
            """
            insert into articles (source_id, url, title, feed_summary, body, published_at, status, status_reason)
            values (:source_id, :url, :title, :feed_summary, :body, :published_at, :status, :reason)
            on conflict (url) do nothing
            returning id
            """,
            source_id=a.source.id, url=a.url, title=a.title, feed_summary=a.feed_summary,
            body=a.body, published_at=a.published_at, status=status, reason=a.error,
        )
        counts["saved" if rows else "already_stored"] += 1
        counts[f"status_{status}"] += 1 if rows else 0
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fetcher", choices=FETCHERS, help="run only one fetcher agent")
    p.add_argument("--limit", type=int, help="max new items per source")
    p.add_argument("--check-feeds", action="store_true", help="only read the feeds")
    p.add_argument("--dry-run", action="store_true", help="download articles but save nothing")
    args = p.parse_args(argv)

    since = datetime.now(UTC) - timedelta(hours=get_settings().lookback_hours)
    sources = load_sources(args.fetcher)
    print(f"Reading {len(sources)} feeds (items since {since:%Y-%m-%d %H:%M} UTC)")

    if args.check_feeds or args.dry_run:
        items, feed_errors = read_feeds(sources, since, args.limit)
        if args.check_feeds:
            return 1 if feed_errors else 0
        articles = fetch_bodies(items)
        for a in articles:
            state = f"{len(a.body):>6} chars" if a.body else f"SKIPPED {a.error}"
            print(f"- [{a.source.name}] {a.title[:70]}  ({state})")
        ok = sum(1 for a in articles if a.body)
        print(f"\nExtracted text for {ok} of {len(articles)} articles. Nothing was saved (dry run).")
        return 0

    from gooddaynews.db import connect

    conn = connect()
    try:
        run_id = conn.run("insert into run_log (stage) values ('fetch') returning id")[0][0]
        sources = sync_sources(conn, sources)
        items, feed_errors = read_feeds(sources, since, args.limit)

        known = {r[0] for r in conn.run("select url from articles where url = any(:urls)", urls=[a.url for a in items])} if items else set()
        new_items = [a for a in items if a.url not in known]
        print(f"{len(new_items)} new articles to download ({len(items) - len(new_items)} already stored)")

        counts = save(conn, fetch_bodies(new_items))
        for s in sources:
            conn.run(
                "update sources set last_checked = now(), last_error = :err where id = :id",
                err=feed_errors.get(s.domain), id=s.id,
            )
        conn.run(
            "update run_log set finished_at = now(), counts = cast(:counts as jsonb), errors = cast(:errors as jsonb) where id = :id",
            counts=json.dumps(dict(counts, feeds=len(sources), feed_errors=len(feed_errors))),
            errors=json.dumps([{"source": k, "error": v} for k, v in feed_errors.items()]),
            id=run_id,
        )
        print(f"Done: {dict(counts)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
