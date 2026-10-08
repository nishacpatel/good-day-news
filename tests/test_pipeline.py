from dataclasses import replace

from gooddaynews.process.pipeline import process
from tests.conftest import FakeLLM, make_article, make_assessment, topic_vector


def test_duplicates_become_one_story_reported_by_two_sources(cfg, pillars):
    articles = [
        make_article("Solar co-op powers village", "a.org", credibility=5),
        make_article("Village solar co-op success", "b.org"),
        make_article("Whale numbers recover", "c.org"),
    ]
    llm = FakeLLM()
    result = process(llm, articles, cfg, pillars)

    assert len(result.drafts) == 2
    solar = next(d for d in result.drafts if len(d.articles) == 2)
    assert solar.distinct_sources == ["a.org", "b.org"]
    assert solar.verification_level == "multiple_sources"
    # The story is written from the most credible source.
    assert "Source: a.org" in llm.scoring_prompts[0]
    assert "b.org: Village solar co-op success" in llm.scoring_prompts[0]


def test_triage_drops_obvious_non_candidates_before_scoring(cfg, pillars):
    result = process(FakeLLM(), [make_article("Crime wave in city"), make_article("Library opens")], cfg, pillars)
    assert [a.title for a, _ in result.triage_rejected] == ["Crime wave in city"]
    assert len(result.drafts) == 1


def test_failed_triage_defers_articles_for_next_run(cfg, pillars):
    result = process(FakeLLM(fail_triage=True), [make_article("Library opens")], cfg, pillars)
    assert [a.title for a in result.deferred] == ["Library opens"]
    assert not result.drafts and result.errors


def test_scoring_failure_is_recorded_not_raised(cfg, pillars):
    result = process(FakeLLM(fail_scoring=True), [make_article("Library opens")], cfg, pillars)
    assert result.drafts[0].error.startswith("scoring failed")
    assert not result.drafts[0].chunks


def test_new_coverage_joins_a_recent_story(cfg, pillars):
    recent = [(42, topic_vector("solar co-op story"))]
    result = process(FakeLLM(), [make_article("Solar co-op expands", "d.org")], cfg, pillars, recent)
    assert not result.drafts
    assert result.attachments[0].story_id == 42
    assert result.attachments[0].chunks and len(result.attachments[0].chunk_vectors) == len(result.attachments[0].chunks)


def test_kept_stories_get_embedding_and_chunks_rejected_do_not(cfg, pillars):
    kept = process(FakeLLM(), [make_article("Library opens")], cfg, pillars).drafts[0]
    assert kept.keep and kept.embedding is not None
    assert kept.chunks and len(kept.chunk_vectors) == len(kept.chunks)

    rejected = process(FakeLLM(make_assessment(constructive=False, reject_reason="no progress")),
                       [make_article("Library opens")], cfg, pillars).drafts[0]
    assert not rejected.keep and rejected.embedding is None and not rejected.chunks


def test_cap_on_new_stories_defers_the_rest(cfg, pillars):
    small_cap = replace(cfg, max_new_stories_per_run=1)
    articles = [make_article("Solar co-op", "a.org"), make_article("Solar plant", "b.org"), make_article("Whale count")]
    result = process(FakeLLM(), articles, small_cap, pillars)
    # The event reported by two sources is scored first; the other waits for the next run.
    assert len(result.drafts) == 1 and len(result.drafts[0].articles) == 2
    assert [a.title for a in result.deferred] == ["Whale count"]


def test_embedding_calls_are_batched(cfg, pillars):
    llm = FakeLLM()
    process(llm, [make_article("Library opens"), make_article("Whale count", "w.org")], cfg, pillars)
    assert len(llm.embed_calls) == 2  # one for clustering, one for stories + chunks
