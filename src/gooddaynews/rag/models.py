"""Records used by the chat engine."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    """Step 1 output: what the user is asking for."""

    standalone_question: str = Field(description="the question rewritten to make sense without the conversation")
    intent: Literal["news_search", "story_followup", "verification", "personal", "out_of_scope"]
    broad: bool = Field(description="true for overview requests with no specific topic, e.g. 'what good happened this week?'")
    keywords: list[str] = Field(description="2-6 search terms: names, places, topics; no filler words")
    start_date: str = Field(description="YYYY-MM-DD start of the time range asked about, or ''")
    end_date: str = Field(description="YYYY-MM-DD end of the time range asked about, or ''")
    pillars: list[str] = Field(description="pillar keys the question is limited to, or []")
    countries: list[str] = Field(description="ISO 3166-1 alpha-2 codes the question is limited to, or []")


@dataclass
class Filters:
    """Constraints from the app (category chips, date picker) or inferred from the question."""

    pillars: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    start: date | None = None
    end: date | None = None


@dataclass
class Source:
    name: str
    url: str


@dataclass
class StoryHit:
    id: int
    headline: str
    summary: str
    why_it_matters: str
    key_facts: list[str]
    pillar: str
    country: str | None
    place: str | None
    published_at: datetime | None
    score: float
    verification_level: str
    source_count: int
    similarity: float = 0.0
    keyword_rank: float = 0.0
    relevance: float = 0.0  # fused rank signal, 0-1
    final: float = 0.0
    sources: list[Source] = field(default_factory=list)


@dataclass
class Passage:
    story_id: int
    text: str
    similarity: float


@dataclass
class Citation:
    number: int
    story: StoryHit


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str


@dataclass
class ChatSession:
    """Context kept within one conversation (PRD section 19)."""

    turns: list[Turn] = field(default_factory=list)
    last_story_ids: list[int] = field(default_factory=list)

    def add(self, role: str, text: str, keep: int) -> None:
        self.turns.append(Turn(role, text))
        del self.turns[: -keep * 2]
