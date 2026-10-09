"""Build, cache and fetch a user's morning briefing."""

from datetime import date

from gooddaynews.briefing import store
from gooddaynews.briefing.builder import briefing_title, select_stories
from gooddaynews.briefing.models import Briefing, BriefingConfig, Profile
from gooddaynews.briefing.prompts import THOUGHT_SYSTEM, Thought, thought_prompt
from gooddaynews.process.config import ScoringConfig


def build_briefing(conn, llm, profile: Profile, cfg: BriefingConfig, scoring: ScoringConfig,
                   today: date | None = None) -> Briefing | None:
    """Pick today's stories for this user and save the briefing. None when there are no stories at all."""
    today = today or profile.local_date()
    signals = store.load_signals(conn, profile.id)
    wanted = cfg.lengths.get(profile.briefing_length, cfg.lengths["standard"])

    chosen, window = [], cfg.window_hours[0]
    for hours in cfg.window_hours:  # widen the window until there are enough stories
        window = hours
        chosen = select_stories(store.recent_stories(conn, hours), profile, cfg,
                                scoring.max_stories_per_pillar, scoring.max_stories_per_country, signals)
        if len(chosen) >= wanted:
            break
    if not chosen:
        return None

    thought = None
    if llm is not None:
        try:
            thought = llm.generate_json(thought_prompt(chosen), Thought, system=THOUGHT_SYSTEM, fast=True).thought.strip()
        except Exception:
            thought = None  # the briefing is still useful without its closing line

    briefing = Briefing(profile.id, today, chosen, briefing_title(len(chosen)), thought or None, window)
    store.save_briefing(conn, briefing)
    return briefing


def get_briefing(conn, llm, profile: Profile, cfg: BriefingConfig, scoring: ScoringConfig,
                 rebuild: bool = False) -> Briefing | None:
    """Today's briefing: the saved one, else build it, else fall back to the most recent earlier one."""
    today = profile.local_date()
    if not rebuild:
        saved = store.load_briefing(conn, profile.id, today)
        if saved and not saved.is_fallback:
            return saved
    try:
        built = build_briefing(conn, llm, profile, cfg, scoring, today)
        if built:
            return built
    except Exception:
        pass
    return store.load_briefing(conn, profile.id, today)
