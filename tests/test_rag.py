from datetime import UTC, date, datetime, timedelta

import pytest

from gooddaynews.rag import engine as engine_mod
from gooddaynews.rag.config import load_rag
from gooddaynews.rag.engine import Answer, ChatEngine, finalize_citations, merge_filters
from gooddaynews.rag.models import ChatSession, Filters, Passage, QueryPlan, StoryHit
from gooddaynews.rag.rank import pick_passages, reciprocal_rank_fusion, recency, rerank
from gooddaynews.rag.retrieve import keyword_query

TODAY = date(2026, 10, 8)
NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


@pytest.fixture
def rag_cfg():
    return load_rag()


def story(id, headline="Story", pillar="environment", days_old=1, score=7.0, relevance=0.5):
    return StoryHit(id=id, headline=headline, summary="s", why_it_matters="w", key_facts=[], pillar=pillar,
                    country="IN", place=None, published_at=NOW - timedelta(days=days_old), score=score,
                    verification_level="single_source", source_count=1, relevance=relevance)


def plan(**kw):
    base = dict(standalone_question="q", intent="news_search", broad=False, keywords=[], start_date="",
                end_date="", pillars=[], countries=[])
    return QueryPlan(**(base | kw))


# ---------- ranking ----------

def test_rrf_rewards_items_ranked_high_in_both_lists():
    fused = reciprocal_rank_fusion([1, 2, 3], [3, 1])
    assert fused[1] == 1.0 and fused[1] > fused[3] > fused[2]
    assert reciprocal_rank_fusion([], []) == {}


def test_recency_halves_every_half_life():
    assert recency(NOW, 7, NOW) == 1.0
    assert recency(NOW - timedelta(days=7), 7, NOW) == pytest.approx(0.5)
    assert recency(None, 7, NOW) == 0.0


def test_rerank_prefers_recent_and_user_topics(rag_cfg):
    old = story(1, days_old=60)
    new = story(2, days_old=0)
    assert [s.id for s in rerank([old, new], rag_cfg, now=NOW)] == [2, 1]

    a, b = story(3, pillar="science"), story(4, pillar="culture")
    assert rerank([a, b], rag_cfg, user_topics=["culture"], now=NOW)[0].id == 4


def test_pick_passages_limits_each_story(rag_cfg):
    passages = [Passage(1, f"p{i}", 0.9 - i / 100) for i in range(6)] + [Passage(2, "other", 0.5)]
    picked = pick_passages(passages, rag_cfg)
    assert sum(p.story_id == 1 for p in picked) == rag_cfg.max_passages_per_story
    assert any(p.story_id == 2 for p in picked)


def test_keyword_query_keeps_phrases_and_strips_operators():
    assert keyword_query(["solar", "Western Ghats", "a-b", ""]) == 'solar OR "Western Ghats" OR "a b"'


# ---------- filters ----------

def test_app_filters_override_question_filters(rag_cfg, pillars):
    p = plan(countries=["IN"], start_date="2026-10-01")
    f = merge_filters(Filters(countries=["GB"]), p, pillars, rag_cfg, TODAY)
    assert f.countries == ["GB"] and f.start == date(2026, 10, 1)


def test_guessed_categories_never_filter(rag_cfg, pillars):
    """Regression (evaluation A6): the model filed a vaccine question under science/solutions, which hid the
    answer filed under progress. Only categories picked in the app may filter."""
    f = merge_filters(None, plan(pillars=["science", "solutions"]), pillars, rag_cfg, TODAY)
    assert f.pillars == []
    assert merge_filters(Filters(pillars=["progress"]), plan(), pillars, rag_cfg, TODAY).pillars == ["progress"]


def test_broad_question_without_dates_gets_default_window(rag_cfg, pillars):
    f = merge_filters(None, plan(broad=True), pillars, rag_cfg, TODAY)
    assert f.start == TODAY - timedelta(days=rag_cfg.default_days_back)


def test_bad_country_codes_and_dates_are_ignored(rag_cfg, pillars):
    f = merge_filters(None, plan(countries=["India"], start_date="last week"), pillars, rag_cfg, TODAY)
    assert f.countries == [] and f.start is None


# ---------- citations ----------

def test_invalid_citations_are_removed_and_valid_ones_mapped():
    a = Answer("q", None, stories=[story(10), story(11)], text="Fact one [1]. Fact two [2][7].")
    finalize_citations(a, "I couldn't find enough reliable reporting to answer that confidently.")
    assert a.text == "Fact one [1]. Fact two [2]."
    assert [(c.number, c.story.id) for c in a.citations] == [(1, 10), (2, 11)]


def test_refusal_text_becomes_a_refusal():
    msg = "I couldn't find enough reliable reporting to answer that confidently."
    a = Answer("q", None, stories=[story(1)], text=msg)
    finalize_citations(a, msg)
    assert a.refused and a.citations == []


def test_stream_failure_shows_unavailable_message():
    def broken():
        yield "Partial"
        raise RuntimeError("quota")

    a = Answer("q", None, _pieces=broken())
    text = "".join(a.stream())
    assert a.kind == "error" and engine_mod.UNAVAILABLE_MESSAGE in text


def test_empty_stream_is_an_error_not_a_blank_answer():
    a = Answer("q", None, _pieces=iter([]))
    a.complete()
    assert a.kind == "error" and a.text == engine_mod.UNAVAILABLE_MESSAGE


# ---------- engine, with fake database searches ----------

class ChatLLM:
    def __init__(self, plan_obj, answer="Answer text [1]."):
        self.plan_obj, self.answer, self.streamed = plan_obj, answer, 0

    def generate_json(self, prompt, schema, *, system, fast=False):
        return self.plan_obj

    def embed(self, texts, task="RETRIEVAL_DOCUMENT"):
        return [[0.0]] * len(texts)

    def stream_text(self, prompt, *, system):
        self.streamed += 1
        self.last_prompt = prompt
        yield self.answer


class _Conn:
    def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    """Story 1 is about solar, story 2 about whales. Searches return whatever `hits` holds."""
    db = {"vector": [], "keyword": [], "recent": []}
    stories = {1: story(1, "Solar co-op"), 2: story(2, "Whale recovery")}
    r = engine_mod.retrieve
    monkeypatch.setattr(r, "story_vector_search", lambda conn, q, f, n: db["vector"])
    monkeypatch.setattr(r, "story_keyword_search", lambda conn, k, f, n: db["keyword"])
    monkeypatch.setattr(r, "recent_story_ids", lambda conn, f, n: db["recent"])
    monkeypatch.setattr(r, "load_stories", lambda conn, ids: {i: stories[i] for i in ids if i in stories})
    monkeypatch.setattr(r, "passage_search", lambda conn, q, ids, n: [Passage(i, "text", 0.8) for i in ids])
    return db


def make_engine(llm, pillars):
    return ChatEngine(llm, lambda: _Conn(), pillars, today=lambda: TODAY)


def test_no_relevant_story_refuses_without_calling_the_answer_model(fake_db, pillars):
    fake_db["vector"] = [(1, 0.40), (2, 0.38)]  # below the similarity threshold
    llm = ChatLLM(plan())
    a = make_engine(llm, pillars).ask("What did the RBI announce?", ChatSession()).complete()
    assert a.refused and llm.streamed == 0


def test_out_of_scope_request(fake_db, pillars):
    llm = ChatLLM(plan(intent="out_of_scope"))
    a = make_engine(llm, pillars).ask("Write a poem", ChatSession()).complete()
    assert a.kind == "out_of_scope" and llm.streamed == 0


def test_relevant_story_is_answered_and_cited(fake_db, pillars):
    fake_db["vector"] = [(1, 0.75), (2, 0.40)]
    llm = ChatLLM(plan())
    session = ChatSession()
    a = make_engine(llm, pillars).ask("Solar news?", session).complete()
    assert [s.id for s in a.stories] == [1]
    assert [c.story.id for c in a.citations] == [1]
    assert session.last_story_ids == [1] and len(session.turns) == 2


def test_keyword_match_alone_is_not_enough(fake_db, pillars):
    fake_db["vector"] = [(2, 0.30)]
    fake_db["keyword"] = [(2, 0.9)]  # shares a word but means something else
    a = make_engine(ChatLLM(plan(keywords=["India"])), pillars).ask("Cricket in India?", ChatSession()).complete()
    assert a.refused


def test_follow_up_can_switch_to_a_different_story(fake_db, pillars):
    fake_db["vector"] = [(2, 0.80)]
    session = ChatSession(last_story_ids=[1])
    a = make_engine(ChatLLM(plan(intent="story_followup")), pillars).ask("Tell me about the whale one", session)
    assert a.stories[0].id == 2  # the newly matched story outranks the previous answer's story


def test_story_in_view_is_always_included(fake_db, pillars):
    fake_db["vector"] = [(2, 0.80)]
    a = make_engine(ChatLLM(plan(intent="story_followup")), pillars).ask("Why does this matter?", ChatSession(), story_id=1)
    assert 1 in [s.id for s in a.stories]


def test_broad_question_uses_recent_stories(fake_db, pillars):
    fake_db["recent"] = [2, 1]
    a = make_engine(ChatLLM(plan(broad=True)), pillars).ask("What good happened this week?", ChatSession()).complete()
    assert {s.id for s in a.stories} == {1, 2} and not a.refused


def test_guessed_category_boosts_ranking(fake_db, pillars, monkeypatch):
    fake_db["vector"] = [(1, 0.70), (2, 0.70)]
    stories = engine_mod.retrieve.load_stories(None, [1, 2])
    stories[1].pillar, stories[2].pillar = "science", "progress"
    monkeypatch.setattr(engine_mod.retrieve, "load_stories", lambda conn, ids: {i: stories[i] for i in ids})
    a = make_engine(ChatLLM(plan(pillars=["progress"])), pillars).ask("q", ChatSession())
    assert a.stories[0].id == 2
