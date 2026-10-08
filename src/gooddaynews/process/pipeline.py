"""Processing + constructive scoring agent: the LLM-driven steps, without database access.

    triage   one cheap call screens a batch of headlines; obvious non-candidates are dropped
    group    embed each candidate; join a recent story or cluster with other articles on the same event
    assess   one call per new story: classify, score 6 dimensions, write summary and key facts
    prepare  chunk the full text of kept stories and embed story + chunks
"""

from dataclasses import dataclass, field

from gooddaynews.llm import LLM
from gooddaynews.process.chunking import chunk_text
from gooddaynews.process.clustering import best_match, cluster
from gooddaynews.process.config import ScoringConfig
from gooddaynews.process.models import ArticleRecord, StoryDraft
from gooddaynews.process.prompts import SCORING_SYSTEM, TRIAGE_SYSTEM, scoring_prompt, triage_prompt
from gooddaynews.process.schemas import StoryAssessment, TriageResult
from gooddaynews.process.scoring import apply_assessment


@dataclass
class Attachment:
    """New articles about an event that already has a story."""

    story_id: int
    articles: list[ArticleRecord]
    chunks: list[tuple[ArticleRecord, int, str]] = field(default_factory=list)
    chunk_vectors: list = field(default_factory=list)


@dataclass
class ProcessResult:
    drafts: list[StoryDraft] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    triage_rejected: list[tuple[ArticleRecord, str]] = field(default_factory=list)
    deferred: list[ArticleRecord] = field(default_factory=list)  # left for the next run
    errors: list[tuple[ArticleRecord, str]] = field(default_factory=list)


def triage(llm: LLM, articles: list[ArticleRecord], cfg: ScoringConfig, result: ProcessResult) -> list[ArticleRecord]:
    candidates = []
    for start in range(0, len(articles), cfg.triage_batch_size):
        batch = articles[start : start + cfg.triage_batch_size]
        items = [
            {"id": i, "source": a.source_name, "title": a.title, "summary": (a.feed_summary or a.body)[:300]}
            for i, a in enumerate(batch)
        ]
        try:
            decisions = {d.id: d for d in llm.generate_json(triage_prompt(items), TriageResult, system=TRIAGE_SYSTEM, fast=True).items}
        except Exception as exc:
            # Leave the batch for the next run rather than dropping it.
            result.deferred.extend(batch)
            result.errors.extend((a, f"triage failed: {exc}"[:300]) for a in batch)
            continue
        for i, a in enumerate(batch):
            d = decisions.get(i)
            if d is None or d.candidate:  # no answer counts as "unsure", which means candidate
                candidates.append(a)
            else:
                result.triage_rejected.append((a, f"triage: {d.reason}"))
    return candidates


def group(
    llm: LLM,
    candidates: list[ArticleRecord],
    cfg: ScoringConfig,
    recent_stories: list[tuple[int, object]],
    result: ProcessResult,
) -> list[list[ArticleRecord]]:
    if not candidates:
        return []
    for a, v in zip(candidates, llm.embed([a.lead() for a in candidates])):
        a.vector = v

    attached: dict[int, list[ArticleRecord]] = {}
    fresh = []
    for a in candidates:
        story_id = best_match(a.vector, recent_stories, cfg.cluster_similarity)
        if story_id is None:
            fresh.append(a)
        else:
            attached.setdefault(story_id, []).append(a)
    result.attachments.extend(Attachment(sid, arts) for sid, arts in attached.items())

    groups = [[fresh[i] for i in g] for g in cluster([a.vector for a in fresh], cfg.cluster_similarity)]
    # Most widely reported and most credible events first, so the per-run cap keeps the best.
    groups.sort(key=lambda g: (-len({a.source_domain for a in g}), -max(a.credibility for a in g)))
    for g in groups[cfg.max_new_stories_per_run :]:
        result.deferred.extend(g)
    return groups[: cfg.max_new_stories_per_run]


def assess(llm: LLM, draft: StoryDraft, cfg: ScoringConfig, pillars: dict) -> StoryDraft:
    lead = draft.lead_article
    article = {
        "source": lead.source_name,
        "source_country": lead.source_country,
        "published": lead.published_at.isoformat() if lead.published_at else None,
        "title": lead.title,
        "body": lead.body,
    }
    others = [{"source": a.source_name, "title": a.title} for a in draft.articles if a is not lead]
    try:
        assessment = llm.generate_json(scoring_prompt(article, others, pillars), StoryAssessment, system=SCORING_SYSTEM)
    except Exception as exc:
        draft.error = f"scoring failed: {exc}"[:300]
        return draft
    return apply_assessment(draft, assessment, cfg, pillars)


def _chunks_for(articles: list[ArticleRecord], cfg: ScoringConfig) -> list[tuple[ArticleRecord, int, str]]:
    return [
        (a, i, text)
        for a in articles
        for i, text in enumerate(chunk_text(a.body, cfg.chunk_target_tokens, cfg.chunk_max_tokens))
    ]


def prepare(llm: LLM, drafts: list[StoryDraft], attachments: list[Attachment], cfg: ScoringConfig) -> None:
    """Chunk and embed everything that will be stored, in as few embedding calls as possible."""
    kept = [d for d in drafts if d.keep]
    texts: list[str] = []
    for d in kept:
        a = d.assessment
        texts.append(f"{a.headline}\n{a.summary}\n{a.why_it_matters}")
        d.chunks = _chunks_for(d.articles, cfg)
        texts.extend(t for _, _, t in d.chunks)
    for att in attachments:
        att.chunks = _chunks_for(att.articles, cfg)
        texts.extend(t for _, _, t in att.chunks)
    if not texts:
        return

    vectors = iter(llm.embed(texts))
    for d in kept:
        d.embedding = next(vectors)
        d.chunk_vectors = [next(vectors) for _ in d.chunks]
    for att in attachments:
        att.chunk_vectors = [next(vectors) for _ in att.chunks]


def process(
    llm: LLM,
    articles: list[ArticleRecord],
    cfg: ScoringConfig,
    pillars: dict,
    recent_stories: list[tuple[int, object]] | None = None,
    on_progress=None,
) -> ProcessResult:
    result = ProcessResult()
    candidates = triage(llm, articles, cfg, result)
    groups = group(llm, candidates, cfg, recent_stories or [], result)
    for i, g in enumerate(groups, 1):
        draft = assess(llm, StoryDraft(articles=g), cfg, pillars)
        result.drafts.append(draft)
        if on_progress:
            on_progress(i, len(groups), draft)
    try:
        prepare(llm, [d for d in result.drafts if not d.error], result.attachments, cfg)
    except Exception as exc:
        for d in result.drafts:
            if d.keep and not d.error:
                d.error = f"embedding failed: {exc}"[:300]
        result.deferred.extend(a for att in result.attachments for a in att.articles)
        result.attachments = []
    return result
