"""Run the processing + constructive scoring agent.

    python -m gooddaynews.process.run --preview 2     # fetch 2 live articles per source, score, print; no database
    python -m gooddaynews.process.run                 # process new articles from the database and save stories
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta

from gooddaynews.llm import GeminiLLM
from gooddaynews.process.config import load_pillars, load_scoring
from gooddaynews.process.models import ArticleRecord, StoryDraft
from gooddaynews.process.pipeline import ProcessResult, process
from gooddaynews.settings import get_settings


def is_quota_error(message: str) -> bool:
    return "RESOURCE_EXHAUSTED" in message or "daily free-tier limit" in message


def show_progress(i: int, n: int, d: StoryDraft) -> None:
    if d.error:
        print(f"  [{i}/{n}] ERROR   {d.lead_article.title[:70]}  ({d.error})")
        return
    mark = "KEEP  " if d.keep else "REJECT"
    a = d.assessment
    print(f"  [{i}/{n}] {mark} {d.total:5.2f}  {a.pillar:<12} {a.headline[:70]}")
    if not d.keep:
        print(f"                       why: {d.reason}")
    if d.dropped_facts:
        print(f"                       dropped {len(d.dropped_facts)} key fact(s) with numbers not in the source")


def summarize(result: ProcessResult) -> Counter:
    c = Counter(
        triage_rejected=len(result.triage_rejected),
        stories_kept=sum(1 for d in result.drafts if d.keep and not d.error),
        stories_rejected=sum(1 for d in result.drafts if not d.keep and not d.error),
        story_errors=sum(1 for d in result.drafts if d.error),
        joined_existing=sum(len(a.articles) for a in result.attachments),
        deferred=len(result.deferred),
        chunks=sum(len(d.chunks) for d in result.drafts) + sum(len(a.chunks) for a in result.attachments),
    )
    return +c


def preview(per_source: int) -> int:
    from gooddaynews.ingest.fetch import fetch_bodies, http_get, parse_feed
    from gooddaynews.ingest.sources import load_sources

    llm = GeminiLLM()  # fail fast if the API key is missing, before downloading anything
    since = datetime.now(UTC) - timedelta(hours=get_settings().lookback_hours)
    items = []
    for s in load_sources():
        try:
            items.extend(parse_feed(s, http_get(s.feed_url), since)[:per_source])
        except Exception as exc:
            print(f"  feed failed: {s.name}: {exc}")
    articles = [
        ArticleRecord(url=a.url, title=a.title, feed_summary=a.feed_summary, body=a.body, published_at=a.published_at,
                      source_name=a.source.name, source_domain=a.source.domain, source_country=a.source.country,
                      credibility=a.source.credibility, is_primary=a.source.primary)
        for a in fetch_bodies(items) if a.body
    ]
    print(f"Processing {len(articles)} live articles (preview: nothing is saved)\n")

    result = process(llm, articles, load_scoring(), load_pillars(), on_progress=show_progress)
    for a, reason in result.triage_rejected:
        print(f"  TRIAGE  {a.title[:70]}  ({reason})")
    kept = [d for d in result.drafts if d.keep and not d.error]
    if kept:
        best = max(kept, key=lambda d: d.total)
        a = best.assessment
        print(f"\nHighest-scoring story:\n  {a.headline}\n  {a.summary}\n  Why it matters: {a.why_it_matters}")
        print(f"  Key facts: {best.key_facts}\n  {best.why_included}")
    print(f"\n{dict(summarize(result))}  LLM calls: {llm.calls} {llm.used}")
    return 0


def run_db(limit: int, dry_run: bool = False) -> int:
    from gooddaynews.db import connect
    from gooddaynews.process import store

    cfg, pillars = load_scoring(), load_pillars()
    conn = connect()
    in_transaction = False
    try:
        run_id = conn.run("insert into run_log (stage) values ('process') returning id")[0][0]
        articles = store.load_new_articles(conn, limit)
        print(f"Processing {len(articles)} new articles")
        recent = store.recent_story_vectors(conn, cfg.cluster_lookback_hours)

        llm = GeminiLLM()
        result = process(llm, articles, cfg, pillars, recent, on_progress=show_progress)
        if dry_run:
            for a, reason in result.triage_rejected:
                print(f"  TRIAGE  {a.title[:70]}  ({reason})")
            print(f"\nDry run, nothing saved: {dict(summarize(result))}  LLM calls: {llm.calls} {llm.used}")
            return 0

        conn.run("BEGIN")
        in_transaction = True
        for a, reason in result.triage_rejected:
            store.mark_articles(conn, [a], "rejected", reason)
        for d in result.drafts:
            if d.error and is_quota_error(d.error):
                continue  # out of daily quota: leave as 'new' so the next run retries
            if d.error:
                store.mark_articles(conn, d.articles, "error", d.error)
            else:
                store.save_draft(conn, d)
        for att in result.attachments:
            store.save_attachment(conn, att)
        retention = store.apply_retention(conn, cfg.retention_days)
        conn.run("COMMIT")
        in_transaction = False

        counts = {**summarize(result), **retention, "llm_calls": llm.calls}
        errors = [{"url": a.url, "error": e} for a, e in result.errors] + [
            {"url": d.lead_article.url, "error": d.error} for d in result.drafts if d.error
        ]
        conn.run(
            "update run_log set finished_at = now(), counts = cast(:c as jsonb), errors = cast(:e as jsonb) where id = :id",
            c=json.dumps(counts), e=json.dumps(errors), id=run_id,
        )
        print(f"Done: {counts}")
    except Exception:
        if in_transaction:
            conn.run("ROLLBACK")
        raise
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preview", type=int, metavar="N", help="score N live articles per source without a database")
    p.add_argument("--limit", type=int, default=200, help="max new articles to process from the database")
    p.add_argument("--dry-run", action="store_true", help="score database articles but save nothing")
    args = p.parse_args(argv)
    return preview(args.preview) if args.preview else run_db(args.limit, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
