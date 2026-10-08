"""RAG settings from config/rag.yaml."""

from dataclasses import dataclass

from gooddaynews.settings import load_yaml


@dataclass(frozen=True)
class RagConfig:
    min_story_similarity: float
    story_candidates: int
    max_stories: int
    max_passages: int
    max_passages_per_story: int
    rerank_weights: dict[str, float]
    preference_boost: float
    recency_half_life_days: float
    default_days_back: int
    history_turns: int
    refusal_message: str


def load_rag() -> RagConfig:
    return RagConfig(**load_yaml("rag.yaml"))
