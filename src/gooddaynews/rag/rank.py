"""Step 4: fuse the two searches and rerank with recency, constructive score and user preference."""

import math
from datetime import UTC, datetime

from gooddaynews.rag.config import RagConfig
from gooddaynews.rag.models import Passage, StoryHit

RRF_K = 60


def reciprocal_rank_fusion(*rankings: list[int]) -> dict[int, float]:
    """Combine ranked id lists; ids ranked high in either list score high. Scaled to 0-1."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for pos, item in enumerate(ranking):
            fused[item] = fused.get(item, 0.0) + 1 / (RRF_K + pos + 1)
    if not fused:
        return {}
    top = max(fused.values())
    return {k: v / top for k, v in fused.items()}


def recency(published_at: datetime | None, half_life_days: float, now: datetime | None = None) -> float:
    if published_at is None:
        return 0.0
    now = now or datetime.now(UTC)
    age_days = max(0.0, (now - published_at).total_seconds() / 86400)
    return math.pow(0.5, age_days / half_life_days)


def rerank(stories: list[StoryHit], cfg: RagConfig, user_topics: list[str] | None = None,
           now: datetime | None = None) -> list[StoryHit]:
    w = cfg.rerank_weights
    for s in stories:
        s.final = (
            w["relevance"] * s.relevance
            + w["recency"] * recency(s.published_at, cfg.recency_half_life_days, now)
            + w["constructive"] * (s.score / 10)
            + (cfg.preference_boost if user_topics and s.pillar in user_topics else 0.0)
        )
    return sorted(stories, key=lambda s: s.final, reverse=True)


def pick_passages(passages: list[Passage], cfg: RagConfig) -> list[Passage]:
    """Best passages overall, but no more than a few from any one story."""
    picked, per_story = [], {}
    for p in sorted(passages, key=lambda p: p.similarity, reverse=True):
        if per_story.get(p.story_id, 0) < cfg.max_passages_per_story:
            picked.append(p)
            per_story[p.story_id] = per_story.get(p.story_id, 0) + 1
        if len(picked) == cfg.max_passages:
            break
    return picked
