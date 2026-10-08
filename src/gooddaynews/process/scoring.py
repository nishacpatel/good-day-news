"""Constructive scoring rules (PRD sections 10, 11, 14 and 20). No LLM or database calls here."""

import re

from gooddaynews.process.config import LLM_DIMENSIONS, ScoringConfig
from gooddaynews.process.models import ArticleRecord, StoryDraft
from gooddaynews.process.schemas import StoryAssessment

VERIFICATION_LABELS = {
    "opinion": "Opinion or commentary",
    "multiple_sources": "Reported by {n} independent sources",
    "primary_source": "From the primary source ({source})",
    "research": "Based on published research, single report",
    "official_data": "Based on official data, single report",
    "single_source": "Reported by one source",
}

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def clamp(value: float, low: float = 0, high: float = 10) -> float:
    return max(low, min(high, value))


def source_credibility(articles: list[ArticleRecord]) -> float:
    """Registry credibility (1-5) of the best source in the cluster, on the 0-10 scale."""
    return clamp(max(a.credibility for a in articles) * 2)


def dimension_scores(assessment: StoryAssessment, articles: list[ArticleRecord]) -> dict[str, float]:
    scores = {d: clamp(getattr(assessment.scores, d)) for d in LLM_DIMENSIONS}
    scores["source_credibility"] = source_credibility(articles)
    return scores


def weighted_total(scores: dict[str, float], weights: dict[str, float]) -> float:
    return round(sum(scores[d] * w for d, w in weights.items()), 2)


def verification(articles: list[ArticleRecord], assessment: StoryAssessment) -> tuple[str, str]:
    """How well-supported the story is. Explains the basis instead of inventing a confidence score."""
    domains = {a.source_domain for a in articles}
    if assessment.is_opinion:
        level = "opinion"
    elif len(domains) >= 2:
        level = "multiple_sources"
    elif any(a.is_primary for a in articles):
        level = "primary_source"
    elif assessment.evidence_basis in ("research", "official_data"):
        level = assessment.evidence_basis
    else:
        level = "single_source"
    primary = next((a.source_name for a in articles if a.is_primary), "")
    return level, VERIFICATION_LABELS[level].format(n=len(domains), source=primary)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER_RE.findall(text)}


def ground_key_facts(facts: list[str], bodies: list[str]) -> tuple[list[str], list[str]]:
    """Keep facts whose numbers all appear in the source text; drop the rest (hallucination guard)."""
    source_numbers = _numbers(" ".join(bodies))
    kept, dropped = [], []
    for fact in facts:
        fact = fact.strip()
        if not fact:
            continue
        (kept if _numbers(fact) <= source_numbers else dropped).append(fact)
    return kept, dropped


def decide(assessment: StoryAssessment, total: float, cfg: ScoringConfig, pillars: dict) -> tuple[bool, str]:
    if not assessment.constructive:
        return False, f"not constructive: {assessment.reject_reason or 'no reason given'}"
    if cfg.reject_opinion and assessment.is_opinion:
        return False, "opinion or commentary"
    if assessment.pillar not in pillars:
        return False, f"unknown pillar {assessment.pillar!r}"
    if total < cfg.keep_threshold:
        return False, f"score {total:.2f} below threshold {cfg.keep_threshold:.2f}"
    return True, "kept"


def why_included(draft: StoryDraft, cfg: ScoringConfig, pillars: dict) -> str:
    """Plain-language record of why a story was kept (PRD section 37)."""
    a = draft.assessment
    top = sorted(((d, s) for d, s in draft.scores.items()), key=lambda x: (-x[1] * cfg.weights[x[0]], x[0]))[:3]
    strengths = ", ".join(f"{d.replace('_', ' ')} {s:g}/10" for d, s in top)
    pillar = pillars.get(a.pillar, {}).get("label", a.pillar)
    return (
        f"Scored {draft.total:.2f}/10 (threshold {cfg.keep_threshold:g}). "
        f"Strongest: {strengths}. Pillar: {pillar} / {a.subcategory}. {draft.verification_label}."
    )


def apply_assessment(draft: StoryDraft, assessment: StoryAssessment, cfg: ScoringConfig, pillars: dict) -> StoryDraft:
    """Fill a draft from the LLM's assessment using the rules above."""
    draft.assessment = assessment
    draft.scores = dimension_scores(assessment, draft.articles)
    draft.total = weighted_total(draft.scores, cfg.weights)
    draft.verification_level, draft.verification_label = verification(draft.articles, assessment)
    draft.key_facts, draft.dropped_facts = ground_key_facts(assessment.key_facts, [a.body for a in draft.articles])
    draft.keep, draft.reason = decide(assessment, draft.total, cfg, pillars)
    if draft.keep:
        draft.why_included = why_included(draft, cfg, pillars)
    return draft
