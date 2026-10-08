"""In-memory records passed between processing steps."""

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from gooddaynews.process.schemas import StoryAssessment


@dataclass
class ArticleRecord:
    url: str
    title: str
    feed_summary: str
    body: str
    published_at: datetime | None
    source_name: str
    source_domain: str
    source_country: str
    credibility: int
    is_primary: bool
    id: int | None = None
    vector: np.ndarray | None = None

    def lead(self, chars: int = 600) -> str:
        """Title plus opening text: what clustering compares."""
        return f"{self.title}\n{(self.feed_summary or self.body)[:chars]}"


@dataclass
class StoryDraft:
    articles: list[ArticleRecord]
    assessment: StoryAssessment | None = None
    scores: dict[str, float] = field(default_factory=dict)
    total: float = 0.0
    keep: bool = False
    reason: str = ""
    verification_level: str = ""
    verification_label: str = ""
    key_facts: list[str] = field(default_factory=list)
    dropped_facts: list[str] = field(default_factory=list)
    why_included: str = ""
    embedding: np.ndarray | None = None
    chunks: list[tuple[ArticleRecord, int, str]] = field(default_factory=list)
    chunk_vectors: list[np.ndarray] = field(default_factory=list)
    error: str | None = None

    @property
    def lead_article(self) -> ArticleRecord:
        """The article the story is written from: most credible source, then longest text."""
        return max(self.articles, key=lambda a: (a.credibility, a.is_primary, len(a.body)))

    @property
    def distinct_sources(self) -> list[str]:
        return sorted({a.source_domain for a in self.articles})

    @property
    def published_at(self) -> datetime | None:
        dates = [a.published_at for a in self.articles if a.published_at]
        return min(dates) if dates else None
