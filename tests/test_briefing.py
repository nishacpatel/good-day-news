from datetime import UTC, date, datetime

import pytest

from gooddaynews.briefing import service
from gooddaynews.briefing.builder import (briefing_title, diversify, rank_stories, select_stories, user_countries,
                                          user_pillars)
from gooddaynews.briefing.models import Briefing, BriefingStory, Profile, load_briefing_config
from gooddaynews.briefing.prompts import Thought


@pytest.fixture
def bcfg():
    return load_briefing_config()


def bstory(id, pillar="science", country="IN", score=7.0):
    return BriefingStory(id=id, headline=f"Story {id}", summary="s", why_it_matters="w", pillar=pillar,
                         subcategory=None, country=country, place=None, published_at=datetime(2026, 10, 8, tzinfo=UTC),
                         score=score, verification_level="single_source", source_count=1)


def profile(**kw):
    return Profile(**({"id": "u1", "email": "a@b.com", "topics": [], "geography": []} | kw))


def test_topics_map_to_pillars(bcfg):
    assert user_pillars(profile(topics=["AI", "Animals"]), bcfg) == {"innovation", "science", "environment", "culture"}


def test_global_means_no_geographic_preference(bcfg):
    assert user_countries(profile(geography=["India", "Global"]), bcfg) is None
    assert user_countries(profile(geography=[]), bcfg) is None
    assert user_countries(profile(geography=["India"]), bcfg) == {"IN"}


def test_preferences_lift_matching_stories(bcfg):
    plain = bstory(1, pillar="culture", country="US", score=7.5)
    match = bstory(2, pillar="science", country="IN", score=7.0)
    ranked = rank_stories([plain, match], profile(topics=["Science"], geography=["India"]), bcfg)
    assert [s.id for s in ranked] == [2, 1]


def test_without_preferences_constructive_score_decides(bcfg):
    ranked = rank_stories([bstory(1, score=6.5), bstory(2, score=8.0)], profile(), bcfg)
    assert [s.id for s in ranked] == [2, 1]


def test_feedback_moves_pillars_up_and_down(bcfg):
    liked, disliked = bstory(1, pillar="culture"), bstory(2, pillar="science")
    ranked = rank_stories([disliked, liked], profile(), bcfg, {"culture": 3, "science": -3})
    assert ranked[0].id == 1


def test_diversify_limits_one_pillar_but_fills_if_short():
    ranked = [bstory(i, pillar="science") for i in range(1, 5)] + [bstory(9, pillar="culture", country="US")]
    picked = diversify(ranked, count=3, max_per_pillar=2, max_per_country=3)
    assert [s.id for s in picked] == [1, 2, 9]
    # Not enough variety: the briefing is filled rather than left short.
    picked = diversify([bstory(i) for i in range(1, 5)], count=4, max_per_pillar=2, max_per_country=3)
    assert len(picked) == 4


def test_briefing_length_controls_story_count(bcfg):
    stories = [bstory(i, pillar=p, country=c) for i, (p, c) in enumerate(
        [(p, c) for p in ("science", "culture", "people", "progress", "humanity", "environment", "solutions")
         for c in ("IN", "US")], 1)]
    for length, n in bcfg.lengths.items():
        assert len(select_stories(list(stories), profile(briefing_length=length), bcfg, 2, 3)) == min(n, len(stories))


def test_title_reads_naturally():
    assert briefing_title(7) == "7 things that went right in the world"
    assert briefing_title(1) == "1 thing that went right in the world"


# ---------- service: widening, thought, fallback ----------

class FakeStore:
    def __init__(self, by_window, saved=None):
        self.by_window, self.saved_briefing, self.saved = by_window, saved, []

    def recent_stories(self, conn, hours):
        return [bstory(i, pillar=p) for i, p in enumerate(self.by_window.get(hours, []), 1)]

    def pillar_feedback(self, conn, uid):
        return {}

    def save_briefing(self, conn, b):
        self.saved.append(b)

    def load_briefing(self, conn, uid, d):
        return self.saved_briefing


class ThoughtLLM:
    def __init__(self, fail=False):
        self.fail = fail

    def generate_json(self, prompt, schema, *, system, fast=False):
        if self.fail:
            raise RuntimeError("quota")
        return Thought(thought="Small, steady efforts add up.")


@pytest.fixture
def scoring():
    from gooddaynews.process.config import load_scoring
    return load_scoring()


def use_store(monkeypatch, fake):
    for name in ("recent_stories", "pillar_feedback", "save_briefing", "load_briefing"):
        monkeypatch.setattr(service.store, name, getattr(fake, name))


PILLARS = ["science", "culture", "people", "progress", "humanity", "environment", "solutions"]


def test_window_widens_until_there_are_enough_stories(monkeypatch, bcfg, scoring):
    fake = FakeStore({24: PILLARS[:2], 48: PILLARS[:5], 72: PILLARS})
    use_store(monkeypatch, fake)
    b = service.build_briefing(None, ThoughtLLM(), profile(briefing_length="standard"), bcfg, scoring, date(2026, 10, 9))
    assert b.window_hours == 72 and len(b.stories) == 7
    assert fake.saved == [b] and b.thought == "Small, steady efforts add up."


def test_quick_briefing_stops_at_the_first_window(monkeypatch, bcfg, scoring):
    use_store(monkeypatch, FakeStore({24: PILLARS[:4], 48: PILLARS}))
    b = service.build_briefing(None, None, profile(briefing_length="quick"), bcfg, scoring, date(2026, 10, 9))
    assert b.window_hours == 24 and len(b.stories) == 3 and b.thought is None


def test_failed_thought_still_gives_a_briefing(monkeypatch, bcfg, scoring):
    use_store(monkeypatch, FakeStore({24: PILLARS}))
    b = service.build_briefing(None, ThoughtLLM(fail=True), profile(), bcfg, scoring, date(2026, 10, 9))
    assert b.stories and b.thought is None


def test_no_new_stories_falls_back_to_the_last_briefing(monkeypatch, bcfg, scoring):
    earlier = Briefing("u1", date(2026, 10, 8), [bstory(1)], "1 thing that went right in the world", is_fallback=True)
    use_store(monkeypatch, FakeStore({}, saved=earlier))
    assert service.get_briefing(None, None, profile(), bcfg, scoring) is earlier


def test_saved_briefing_for_today_is_reused(monkeypatch, bcfg, scoring):
    today = profile().local_date()
    saved = Briefing("u1", today, [bstory(1)], "t")
    fake = FakeStore({24: PILLARS}, saved=saved)
    use_store(monkeypatch, fake)
    assert service.get_briefing(None, None, profile(), bcfg, scoring) is saved and fake.saved == []
