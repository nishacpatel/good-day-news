"""Database reads and writes for the processing step."""

import json

import numpy as np
from pgvector import Vector

from gooddaynews.process.models import ArticleRecord, StoryDraft
from gooddaynews.process.pipeline import Attachment


def load_new_articles(conn, limit: int) -> list[ArticleRecord]:
    rows = conn.run(
        """
        select a.id, a.url, a.title, coalesce(a.feed_summary, ''), a.body, a.published_at,
               s.name, s.domain, coalesce(s.country, ''), s.credibility, s.is_primary
        from articles a join sources s on s.id = a.source_id
        where a.status = 'new' and a.body is not null
        order by a.fetched_at
        limit :limit
        """,
        limit=limit,
    )
    return [
        ArticleRecord(id=r[0], url=r[1], title=r[2], feed_summary=r[3], body=r[4], published_at=r[5],
                      source_name=r[6], source_domain=r[7], source_country=r[8], credibility=r[9], is_primary=r[10])
        for r in rows
    ]


def recent_story_vectors(conn, hours: int) -> list[tuple[int, np.ndarray]]:
    rows = conn.run(
        """
        select id, embedding from stories
        where status = 'published' and embedding is not null
          and coalesce(published_at, created_at) > now() - make_interval(hours => :hours)
        """,
        hours=hours,
    )
    return [(r[0], r[1].to_numpy() if isinstance(r[1], Vector) else np.asarray(r[1])) for r in rows]


def mark_articles(conn, articles: list[ArticleRecord], status: str, reason: str | None = None, story_id: int | None = None) -> None:
    for a in articles:
        conn.run(
            "update articles set status = :status, status_reason = :reason, story_id = :story_id where id = :id",
            status=status, reason=reason, story_id=story_id, id=a.id,
        )


def insert_chunks(conn, story_id: int, chunks, vectors) -> int:
    for (article, idx, text), vec in zip(chunks, vectors):
        conn.run(
            """
            insert into chunks (story_id, article_id, chunk_index, content, embedding)
            values (:story_id, :article_id, :idx, :content, cast(:emb as vector))
            on conflict (article_id, chunk_index) do nothing
            """,
            story_id=story_id, article_id=article.id, idx=idx, content=text, emb=vec,
        )
    return len(chunks)


def save_draft(conn, draft: StoryDraft) -> int:
    """Store a scored story (kept or rejected) and link its articles. Returns the story id."""
    a = draft.assessment
    breakdown = {**draft.scores, "total": draft.total, "dropped_facts": draft.dropped_facts,
                 "evidence_basis": a.evidence_basis, "is_opinion": a.is_opinion, "decision": draft.reason}
    story_id = conn.run(
        """
        insert into stories (status, headline, summary, why_it_matters, key_facts, pillar, subcategory, country, place,
                             entities, published_at, score, score_breakdown, verification_level, why_included,
                             source_count, embedding)
        values (:status, :headline, :summary, :why, cast(:facts as jsonb), :pillar, :subcategory, :country, :place,
                cast(:entities as jsonb), :published_at, :score, cast(:breakdown as jsonb), :verification, :why_included,
                :source_count, cast(:emb as vector))
        returning id
        """,
        status="published" if draft.keep else "rejected",
        headline=a.headline, summary=a.summary, why=a.why_it_matters, facts=json.dumps(draft.key_facts),
        pillar=a.pillar, subcategory=a.subcategory, country=a.country or None, place=a.place or None,
        entities=json.dumps(a.entities[:8]), published_at=draft.published_at, score=draft.total,
        breakdown=json.dumps(breakdown), verification=draft.verification_level,
        why_included=draft.why_included or draft.reason, source_count=len(draft.distinct_sources),
        emb=draft.embedding,
    )[0][0]
    if draft.keep:
        mark_articles(conn, draft.articles, "processed", None, story_id)
        insert_chunks(conn, story_id, draft.chunks, draft.chunk_vectors)
    else:
        mark_articles(conn, draft.articles, "rejected", draft.reason, story_id)
    return story_id


def save_attachment(conn, att: Attachment) -> None:
    """Link newly found coverage to an existing story and refresh its source count."""
    mark_articles(conn, att.articles, "processed", "joined existing story", att.story_id)
    insert_chunks(conn, att.story_id, att.chunks, att.chunk_vectors)
    conn.run(
        """
        update stories set
            source_count = (select count(distinct source_id) from articles where story_id = :id),
            verification_level = case
                when verification_level <> 'opinion'
                     and (select count(distinct source_id) from articles where story_id = :id) >= 2
                then 'multiple_sources' else verification_level end,
            updated_at = now()
        where id = :id
        """,
        id=att.story_id,
    )


def apply_retention(conn, days: int) -> dict:
    """Delete full text and chunks older than the retention window (copyright, PRD risk 6)."""
    chunks = conn.run(
        "delete from chunks where created_at < now() - make_interval(days => :days) returning id", days=days
    )
    bodies = conn.run(
        "update articles set body = null where body is not null and fetched_at < now() - make_interval(days => :days) returning id",
        days=days,
    )
    return {"chunks_deleted": len(chunks), "bodies_deleted": len(bodies)}
