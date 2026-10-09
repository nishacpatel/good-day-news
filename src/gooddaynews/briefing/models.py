"""Briefing settings, user profiles and briefings."""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from gooddaynews.settings import load_yaml

LENGTHS = ("quick", "standard", "deep")


@dataclass(frozen=True)
class BriefingConfig:
    lengths: dict[str, int]
    window_hours: list[int]
    topic_boost: float
    geography_boost: float
    feedback_weight: float
    topics: dict[str, list[str]]
    geography: dict[str, list[str]]


def load_briefing_config() -> BriefingConfig:
    return BriefingConfig(**load_yaml("briefing.yaml"))


@dataclass
class Profile:
    id: str
    email: str
    display_name: str | None = None
    topics: list[str] = field(default_factory=list)       # onboarding topics, e.g. "Science"
    geography: list[str] = field(default_factory=list)    # e.g. "India", "Global"
    briefing_length: str = "standard"
    notify_time: time = time(6, 0)
    timezone: str = "Asia/Kolkata"
    notify_enabled: bool = True

    def local_now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def local_date(self) -> date:
        return self.local_now().date()


@dataclass
class BriefingStory:
    id: int
    headline: str
    summary: str
    why_it_matters: str
    pillar: str
    subcategory: str | None
    country: str | None
    place: str | None
    published_at: datetime | None
    score: float
    verification_level: str
    source_count: int
    sources: list[tuple[str, str]] = field(default_factory=list)  # (name, url)
    rank: float = 0.0


@dataclass
class Briefing:
    user_id: str
    for_date: date
    stories: list[BriefingStory]
    title: str
    thought: str | None = None
    window_hours: int = 24
    is_fallback: bool = False  # True when showing an earlier day's briefing
