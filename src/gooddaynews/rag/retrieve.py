"""Database searches for the chat: stories first (step 2), then passages inside them (step 3)."""

import re

from pgvector import Vector

from gooddaynews.rag.models import Filters, Passage, Source, StoryHit

_PUBLISHED = "status = 'published'"


def _filter_sql(f: Filters) -> tuple[str, dict]:
    clauses, params = [_PUBLISHED], {}
    if f.pillars:
        clauses.append("pillar = any(cast(:pillars as text[]))")
        params["pillars"] = f.pillars
    if f.countries:
        clauses.append("country = any(cast(:countries as text[]))")
        params["countries"] = f.countries
    if f.start:
        clauses.append("coalesce(published_at, created_at) >= cast(:start as date)")
        params["start"] = f.start
    if f.end:
        clauses.append("coalesce(published_at, created_at) < cast(:end as date) + 1")
        params["end"] = f.end
    return " and ".join(clauses), params


def keyword_query(keywords: list[str]) -> str:
    """websearch_to_tsquery text matching ANY keyword; phrases stay together."""
    terms = []
    for k in keywords:
        k = re.sub(r"[\"'()|&!:<>-]", " ", k).strip()
        if k:
            terms.append(f'"{k}"' if " " in k else k)
    return " OR ".join(terms)


def story_vector_search(conn, qvec, f: Filters, limit: int) -> list[tuple[int, float]]:
    where, params = _filter_sql(f)
    rows = conn.run(
        f"""select id, 1 - (embedding <=> cast(:q as vector)) from stories
            where {where} and embedding is not null
            order by embedding <=> cast(:q as vector) limit :limit""",
        q=qvec, limit=limit, **params,
    )
    return [(r[0], float(r[1])) for r in rows]


def story_keyword_search(conn, keywords: list[str], f: Filters, limit: int) -> list[tuple[int, float]]:
    query = keyword_query(keywords)
    if not query:
        return []
    where, params = _filter_sql(f)
    rows = conn.run(
        f"""select id, ts_rank_cd(tsv, websearch_to_tsquery('english', :kw)) as r from stories
            where {where} and tsv @@ websearch_to_tsquery('english', :kw)
            order by r desc limit :limit""",
        kw=query, limit=limit, **params,
    )
    return [(r[0], float(r[1])) for r in rows]


def recent_story_ids(conn, f: Filters, limit: int) -> list[int]:
    """For broad questions: the best recent stories within the filters."""
    where, params = _filter_sql(f)
    rows = conn.run(
        f"select id from stories where {where} order by score desc, published_at desc nulls last limit :limit",
        limit=limit, **params,
    )
    return [r[0] for r in rows]


def load_stories(conn, ids: list[int]) -> dict[int, StoryHit]:
    if not ids:
        return {}
    rows = conn.run(
        """select id, headline, coalesce(summary, ''), coalesce(why_it_matters, ''), key_facts, coalesce(pillar, ''),
                  country, place, coalesce(published_at, created_at), coalesce(score, 0), coalesce(verification_level, ''),
                  source_count
           from stories where id = any(cast(:ids as bigint[])) and status = 'published'""",
        ids=ids,
    )
    stories = {
        r[0]: StoryHit(id=r[0], headline=r[1], summary=r[2], why_it_matters=r[3], key_facts=list(r[4] or []),
                       pillar=r[5], country=r[6], place=r[7], published_at=r[8], score=float(r[9]),
                       verification_level=r[10], source_count=r[11])
        for r in rows
    }
    for story_id, name, url in conn.run(
        """select a.story_id, s.name, a.url from articles a join sources s on s.id = a.source_id
           where a.story_id = any(cast(:ids as bigint[])) order by s.credibility desc, a.published_at""",
        ids=list(stories),
    ):
        stories[story_id].sources.append(Source(name, url))
    return stories


def passage_search(conn, qvec, story_ids: list[int], limit: int) -> list[Passage]:
    if not story_ids:
        return []
    rows = conn.run(
        """select story_id, content, 1 - (embedding <=> cast(:q as vector)) from chunks
           where story_id = any(cast(:ids as bigint[])) and embedding is not null
           order by embedding <=> cast(:q as vector) limit :limit""",
        q=qvec, ids=story_ids, limit=limit,
    )
    return [Passage(r[0], r[1], float(r[2])) for r in rows]


def as_vector(v):
    return v.to_numpy() if isinstance(v, Vector) else v
