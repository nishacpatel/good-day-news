"""Explore, search and story detail (PRD sections 8.3, 22 and 23). No answer generation: search costs at most
one embedding call, and falls back to keyword search if that fails."""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from gooddaynews.briefing.builder import Signals, rank_stories
from gooddaynews.briefing.models import BriefingConfig, BriefingStory, Profile
from gooddaynews.briefing.store import STORY_COLUMNS, stories_with_sources
from gooddaynews.rag import retrieve
from gooddaynews.rag.models import Filters
from gooddaynews.rag.rank import reciprocal_rank_fusion

SORTS = {"newest": "Newest", "constructive": "Most constructive", "popular": "Most liked", "for_you": "For you"}
_TIME_PHRASES = [
    (r"\btoday\b", 0), (r"\byesterday\b", 1), (r"\b(this|past|last) week\b", 7),
    (r"\b(this|past|last) month\b", 30),
]
# Same relevance bar as the chat (config/rag.yaml), so search and chat agree on what is "about" a topic.
MIN_SIMILARITY = 0.62
KEYWORD_MARGIN = 0.05
# Story-to-story similarity runs higher than question-to-story (different stories reach about 0.86).
RELATED_MIN_SIMILARITY = 0.75
GENERIC_WORDS = {"good", "news", "positive", "constructive", "story", "stories", "latest", "recent", "any",
                 "what", "show", "me", "about", "inspiring", "happy", "great", "progress", "things"}


@dataclass
class StoryDetail:
    story: BriefingStory
    key_facts: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    why_included: str = ""
    likes: int = 0
    related: list[BriefingStory] = field(default_factory=list)


def search_terms(query: str) -> list[str]:
    """Words worth keyword-matching. In this app nearly every story is 'good news', so those words match nothing useful."""
    return [w for w in re.findall(r"[\w'-]+", query.lower()) if w not in GENERIC_WORDS and len(w) > 1]


def parse_time_phrase(query: str, today: date) -> tuple[str, date | None]:
    """Turn 'scientific breakthroughs this month' into ('scientific breakthroughs', today - 30 days)."""
    for pattern, days in _TIME_PHRASES:
        if re.search(pattern, query, flags=re.I):
            cleaned = re.sub(pattern, " ", query, flags=re.I)
            return " ".join(cleaned.split()), today - timedelta(days=days)
    return query.strip(), None


def _where(f: Filters, hidden: set[str]) -> tuple[str, dict]:
    where, params = retrieve._filter_sql(f)
    if hidden:
        where += " and pillar <> all(cast(:hidden as text[]))"
        params["hidden"] = sorted(hidden)
    return where, params


def like_counts(conn, story_ids: list[int] | None = None) -> dict[int, int]:
    """Current likes per story: each user's latest reaction counts once."""
    rows = conn.run(
        """select story_id, count(*) from (
               select distinct on (user_id, story_id) story_id, action from feedback
               where action in ('like', 'unlike', 'dislike', 'undislike') and story_id is not null
               order by user_id, story_id, created_at desc, id desc) r
           where action = 'like' group by story_id"""
    )
    counts = {r[0]: int(r[1]) for r in rows}
    return {i: counts.get(i, 0) for i in story_ids} if story_ids is not None else counts


def browse(conn, f: Filters, sort: str, limit: int = 30, hidden: set[str] | None = None,
           profile: Profile | None = None, cfg: BriefingConfig | None = None,
           signals: Signals | None = None) -> list[BriefingStory]:
    where, params = _where(f, hidden or set())
    order = {"newest": "coalesce(published_at, created_at) desc", "constructive": "score desc"}.get(sort, "score desc")
    fetch = limit if sort in ("newest", "constructive") else limit * 4
    rows = conn.run(f"select {STORY_COLUMNS} from stories where {where} order by {order} limit :limit",
                    limit=fetch, **params)
    stories = stories_with_sources(conn, rows)
    order_ids = [r[0] for r in rows]
    stories.sort(key=lambda s: order_ids.index(s.id))
    if sort == "popular":
        likes = like_counts(conn)
        stories.sort(key=lambda s: (likes.get(s.id, 0), s.score), reverse=True)
    elif sort == "for_you" and profile and cfg:
        stories = rank_stories(stories, profile, cfg, signals)
    return stories[:limit]


def search(conn, llm, query: str, f: Filters, limit: int = 20, hidden: set[str] | None = None,
           today: date | None = None) -> list[BriefingStory]:
    """Keyword + meaning search over stories. Returns [] when nothing is genuinely related."""
    query, since = parse_time_phrase(query, today or date.today())
    if since and not f.start:
        f = Filters(pillars=f.pillars, countries=f.countries, start=since, end=f.end)
    if not query:
        return browse(conn, f, "newest", limit, hidden)

    terms = search_terms(query)
    if not terms:  # e.g. "good news this week": nothing specific to search for
        return browse(conn, f, "constructive", limit, hidden)

    sims: dict[int, float] = {}
    semantic: list[int] = []
    keyword_floor = MIN_SIMILARITY - KEYWORD_MARGIN
    try:
        # Embed only the meaningful words: "positive AI news" would otherwise match every positive story.
        qvec = llm.embed([" ".join(terms)], task="RETRIEVAL_QUERY")[0]
        hits = retrieve.story_vector_search(conn, qvec, f, limit * 2)
        sims = dict(hits)
        semantic = [i for i, s in hits if s >= MIN_SIMILARITY]
    except Exception:
        keyword_floor = None  # embedding unavailable: trust keyword matches alone
    # In the search box every word should count, so keyword matches need ALL the words.
    keyword = [i for i, _ in retrieve.story_keyword_search(conn, terms, f, limit * 2, match_all=True)
               if keyword_floor is None or sims.get(i, 0.0) >= keyword_floor]

    fused = reciprocal_rank_fusion(semantic, keyword)
    ids = [i for i, _ in sorted(fused.items(), key=lambda x: x[1], reverse=True)]
    if not ids:
        return []
    where, params = _where(Filters(), hidden or set())
    rows = conn.run(f"select {STORY_COLUMNS} from stories where {where} and id = any(cast(:ids as bigint[]))",
                    ids=ids, **params)
    stories = {s.id: s for s in stories_with_sources(conn, rows)}
    return [stories[i] for i in ids if i in stories][:limit]


def story_detail(conn, story_id: int, related_count: int = 4) -> StoryDetail | None:
    rows = conn.run(f"select {STORY_COLUMNS} from stories where id = :id and status = 'published'", id=story_id)
    if not rows:
        return None
    story = stories_with_sources(conn, rows)[0]
    facts, entities, why = conn.run(
        "select key_facts, entities, coalesce(why_included, '') from stories where id = :id", id=story_id)[0]
    related_rows = conn.run(
        f"""select {STORY_COLUMNS} from stories
            where status = 'published' and id <> :id and embedding is not null
              and 1 - (embedding <=> (select embedding from stories where id = :id)) >= :min
            order by embedding <=> (select embedding from stories where id = :id) limit :n""",
        id=story_id, min=RELATED_MIN_SIMILARITY, n=related_count,
    )
    order = [r[0] for r in related_rows]
    related = sorted(stories_with_sources(conn, related_rows), key=lambda s: order.index(s.id))
    return StoryDetail(story, list(facts or []), list(entities or []), why,
                       like_counts(conn, [story_id])[story_id], related)
