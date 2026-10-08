import pytest

from gooddaynews.process.config import ScoringConfig, load_scoring
from gooddaynews.process.models import StoryDraft
from gooddaynews.process.schemas import DimensionScores
from gooddaynews.process.scoring import (
    apply_assessment,
    decide,
    ground_key_facts,
    source_credibility,
    verification,
    weighted_total,
)
from gooddaynews.settings import load_yaml
from tests.conftest import make_article, make_assessment


def test_weights_must_add_up_to_one():
    raw = load_yaml("scoring.yaml")
    raw["weights"]["novelty"] = 0.5
    with pytest.raises(ValueError, match="add up to 1.0"):
        ScoringConfig.from_dict(raw)


def test_weights_must_cover_every_dimension():
    raw = load_yaml("scoring.yaml")
    del raw["weights"]["novelty"]
    with pytest.raises(ValueError, match="missing"):
        ScoringConfig.from_dict(raw)


def test_weighted_total_uses_configured_weights(cfg):
    assert weighted_total({d: 8 for d in cfg.weights}, cfg.weights) == 8.0
    scores = {d: 0 for d in cfg.weights} | {"constructive_impact": 10}
    assert weighted_total(scores, cfg.weights) == round(10 * cfg.weights["constructive_impact"], 2)


def test_source_credibility_comes_from_best_source():
    assert source_credibility([make_article("a", credibility=3), make_article("b", credibility=5)]) == 10


@pytest.mark.parametrize("articles, overrides, expected", [
    ([make_article("a", "x.org"), make_article("b", "y.org")], {}, "multiple_sources"),
    ([make_article("a", "x.org"), make_article("b", "x.org")], {}, "single_source"),
    ([make_article("a", primary=True)], {}, "primary_source"),
    ([make_article("a")], {"evidence_basis": "research"}, "research"),
    ([make_article("a"), make_article("b", "y.org")], {"is_opinion": True}, "opinion"),
])
def test_verification_level(articles, overrides, expected):
    level, label = verification(articles, make_assessment(**overrides))
    assert level == expected and label


def test_key_facts_with_invented_numbers_are_dropped():
    body = "The project planted 12,500 trees across 3 districts."
    kept, dropped = ground_key_facts(
        ["It planted 12500 trees.", "It covered 3 districts.", "It cost 40 million dollars.", "Volunteers led it."],
        [body],
    )
    assert kept == ["It planted 12500 trees.", "It covered 3 districts.", "Volunteers led it."]
    assert dropped == ["It cost 40 million dollars."]


def test_decide_rejects_non_constructive_opinion_unknown_pillar_and_low_scores(cfg, pillars):
    assert decide(make_assessment(constructive=False, reject_reason="crime report"), 9, cfg, pillars) == (
        False, "not constructive: crime report")
    assert decide(make_assessment(is_opinion=True), 9, cfg, pillars)[1] == "opinion or commentary"
    assert "unknown pillar" in decide(make_assessment(pillar="sport"), 9, cfg, pillars)[1]
    assert "below threshold" in decide(make_assessment(), cfg.keep_threshold - 0.01, cfg, pillars)[1]
    assert decide(make_assessment(), cfg.keep_threshold, cfg, pillars) == (True, "kept")


def test_positive_wording_with_weak_substance_is_not_kept(cfg, pillars):
    weak = DimensionScores(constructive_impact=3, significance=2, human_impact=3, novelty=3,
                           evidence_quality=2, emotional_value=9)
    draft = apply_assessment(StoryDraft([make_article("Heartwarming!", credibility=3)]),
                             make_assessment(scores=weak), cfg, pillars)
    assert not draft.keep and "below threshold" in draft.reason


def test_apply_assessment_fills_a_kept_story(cfg, pillars):
    draft = StoryDraft([make_article("Solar co-op", "a.org", credibility=5), make_article("Solar co-op", "b.org")])
    draft = apply_assessment(draft, make_assessment(), cfg, pillars)
    assert draft.keep
    assert draft.scores["source_credibility"] == 10
    assert draft.verification_level == "multiple_sources"
    assert draft.key_facts == ["The co-op powers 400 homes."]
    assert "Scored" in draft.why_included and "Environment & Planet" in draft.why_included


def test_scores_out_of_range_are_clamped(cfg, pillars):
    wild = DimensionScores(constructive_impact=15, significance=-3, human_impact=8, novelty=6,
                           evidence_quality=7, emotional_value=7)
    draft = apply_assessment(StoryDraft([make_article("x")]), make_assessment(scores=wild), cfg, pillars)
    assert draft.scores["constructive_impact"] == 10 and draft.scores["significance"] == 0


def test_shipped_config_loads():
    cfg = load_scoring()
    assert 0 < cfg.keep_threshold <= 10 and 0 < cfg.cluster_similarity < 1
