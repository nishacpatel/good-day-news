import hashlib
from datetime import UTC, datetime

import numpy as np
import pytest

from gooddaynews.process.config import load_pillars, load_scoring
from gooddaynews.process.models import ArticleRecord
from gooddaynews.process.schemas import DimensionScores, StoryAssessment, TriageItem, TriageResult

DIM = 16
TOPICS = ["solar", "whale", "library", "vaccine"]


def topic_vector(text: str) -> np.ndarray:
    """Texts that mention the same topic word get almost the same vector."""
    text = text.lower()
    seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
    noise = np.random.default_rng(seed).normal(0, 0.05, DIM)
    base = np.zeros(DIM)
    for i, topic in enumerate(TOPICS):
        if topic in text:
            base[i] = 1.0
    if not base.any():
        base = np.random.default_rng(seed).normal(0, 1, DIM)
    v = base + noise
    return v / np.linalg.norm(v)


def make_assessment(**overrides) -> StoryAssessment:
    data = dict(
        constructive=True, reject_reason="", is_opinion=False, evidence_basis="news_reporting",
        pillar="environment", subcategory="Renewable energy", country="IN", place="Kerala",
        entities=["Village co-op"],
        scores=DimensionScores(constructive_impact=8, significance=7, human_impact=8, novelty=6,
                               evidence_quality=7, emotional_value=7),
        headline="Village solar co-op powers 400 homes",
        summary="A community solar co-op now powers 400 homes.",
        why_it_matters="Cheaper, cleaner power for rural households.",
        key_facts=["The co-op powers 400 homes."],
    )
    data.update(overrides)
    return StoryAssessment(**data)


class FakeLLM:
    """Stands in for Gemini. Triage rejects titles containing 'crime'; scoring returns `assessment`."""

    def __init__(self, assessment: StoryAssessment | None = None, fail_triage=False, fail_scoring=False):
        self.assessment = assessment or make_assessment()
        self.fail_triage, self.fail_scoring = fail_triage, fail_scoring
        self.embed_calls: list[list[str]] = []
        self.scoring_prompts: list[str] = []

    def generate_json(self, prompt, schema, *, system, fast=False):
        if schema is TriageResult:
            if self.fail_triage:
                raise RuntimeError("quota exceeded")
            import json
            items = json.loads(prompt.split("\n", 1)[1])
            return TriageResult(items=[
                TriageItem(id=i["id"], candidate="crime" not in i["title"].lower(), reason="crime report")
                for i in items
            ])
        if self.fail_scoring:
            raise RuntimeError("model overloaded")
        self.scoring_prompts.append(prompt)
        return self.assessment

    def embed(self, texts, task="RETRIEVAL_DOCUMENT"):
        self.embed_calls.append(list(texts))
        return [topic_vector(t) for t in texts]


def make_article(title: str, domain: str = "example.org", credibility: int = 4, primary: bool = False,
                 body: str | None = None, id: int | None = None) -> ArticleRecord:
    return ArticleRecord(
        id=id, url=f"https://{domain}/{abs(hash(title))}", title=title, feed_summary=title,
        body=body or f"{title}. The co-op powers 400 homes and saved 1,200 rupees a month per family. " * 40,
        published_at=datetime(2026, 10, 7, tzinfo=UTC), source_name=domain, source_domain=domain,
        source_country="IN", credibility=credibility, is_primary=primary,
    )


@pytest.fixture
def cfg():
    return load_scoring()


@pytest.fixture
def pillars():
    return load_pillars()
