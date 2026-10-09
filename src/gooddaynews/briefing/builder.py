"""Choose and order a user's briefing stories (PRD sections 10, 16-18). No database or LLM calls here."""

from dataclasses import dataclass, field

from gooddaynews.briefing.models import BriefingConfig, BriefingStory, Profile


@dataclass
class Signals:
    """What the user has told us through their actions (PRD section 24)."""

    pillar_reactions: dict[str, int] = field(default_factory=dict)  # net likes per pillar
    hidden_pillars: set[str] = field(default_factory=set)
    followed_pillars: set[str] = field(default_factory=set)
    followed_sources: set[str] = field(default_factory=set)  # source domains


def user_pillars(profile: Profile, cfg: BriefingConfig) -> set[str]:
    return {p for t in profile.topics for p in cfg.topics.get(t, [])}


def user_countries(profile: Profile, cfg: BriefingConfig) -> set[str] | None:
    """Country codes the user prefers, or None when they have no geographic preference."""
    if not profile.geography or "Global" in profile.geography:
        return None
    return {c for g in profile.geography for c in cfg.geography.get(g, [])}


def rank_stories(stories: list[BriefingStory], profile: Profile, cfg: BriefingConfig,
                 signals: Signals | None = None) -> list[BriefingStory]:
    """Constructive score, boosted for the user's topics, geography, follows and likes.
    Stories in topics the user has hidden are left out."""
    signals = signals or Signals()
    pillars = user_pillars(profile, cfg) | signals.followed_pillars
    countries = user_countries(profile, cfg)
    kept = []
    for s in stories:
        if s.pillar in signals.hidden_pillars:
            continue
        boost = 1.0
        if s.pillar in pillars:
            boost += cfg.topic_boost
        if countries is not None and (s.country or "") in countries:
            boost += cfg.geography_boost
        if signals.followed_sources & {src[2] for src in s.sources}:
            boost += cfg.source_boost
        net = max(-3, min(3, signals.pillar_reactions.get(s.pillar, 0)))
        boost += cfg.feedback_weight * net
        s.rank = round(s.score / 10 * max(boost, 0.1), 4)
        kept.append(s)
    return sorted(kept, key=lambda s: (s.rank, s.score), reverse=True)


def diversify(ranked: list[BriefingStory], count: int, max_per_pillar: int, max_per_country: int) -> list[BriefingStory]:
    """Take stories in rank order without over-concentrating on one pillar or country.
    If the limits leave the briefing short, fill it with the best of the skipped stories."""
    chosen, skipped = [], []
    per_pillar: dict[str, int] = {}
    per_country: dict[str, int] = {}
    for s in ranked:
        if len(chosen) == count:
            break
        country = s.country or "?"
        if per_pillar.get(s.pillar, 0) >= max_per_pillar or per_country.get(country, 0) >= max_per_country:
            skipped.append(s)
            continue
        chosen.append(s)
        per_pillar[s.pillar] = per_pillar.get(s.pillar, 0) + 1
        per_country[country] = per_country.get(country, 0) + 1
    chosen += skipped[: count - len(chosen)]
    order = {s.id: i for i, s in enumerate(ranked)}
    return sorted(chosen, key=lambda s: order[s.id])


def select_stories(candidates: list[BriefingStory], profile: Profile, cfg: BriefingConfig,
                   max_per_pillar: int, max_per_country: int,
                   signals: Signals | None = None) -> list[BriefingStory]:
    count = cfg.lengths.get(profile.briefing_length, cfg.lengths["standard"])
    ranked = rank_stories(candidates, profile, cfg, signals)
    return diversify(ranked, count, max_per_pillar, max_per_country)


def briefing_title(count: int) -> str:
    if count == 1:
        return "1 thing that went right in the world"
    return f"{count} things that went right in the world"
