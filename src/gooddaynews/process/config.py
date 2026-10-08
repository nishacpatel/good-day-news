"""Scoring and processing settings from config/scoring.yaml and config/pillars.yaml."""

from dataclasses import dataclass

from gooddaynews.settings import load_yaml

# The six dimensions the LLM scores. Source credibility comes from the source registry instead.
LLM_DIMENSIONS = (
    "constructive_impact",
    "significance",
    "human_impact",
    "novelty",
    "evidence_quality",
    "emotional_value",
)
ALL_DIMENSIONS = LLM_DIMENSIONS + ("source_credibility",)


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, float]
    keep_threshold: float
    reject_opinion: bool
    cluster_similarity: float
    cluster_lookback_hours: int
    triage_batch_size: int
    max_new_stories_per_run: int
    chunk_target_tokens: int
    chunk_max_tokens: int
    retention_days: int
    max_stories_per_pillar: int
    max_stories_per_country: int

    @classmethod
    def from_dict(cls, raw: dict) -> "ScoringConfig":
        weights = {k: float(v) for k, v in raw["weights"].items()}
        if set(weights) != set(ALL_DIMENSIONS):
            missing, extra = set(ALL_DIMENSIONS) - set(weights), set(weights) - set(ALL_DIMENSIONS)
            raise ValueError(f"scoring.yaml weights: missing {sorted(missing)}, unknown {sorted(extra)}")
        if abs(sum(weights.values()) - 1.0) > 0.001:
            raise ValueError(f"scoring.yaml weights must add up to 1.0 (they add up to {sum(weights.values()):.3f})")
        return cls(weights=weights, **{k: v for k, v in raw.items() if k != "weights"})


def load_scoring() -> ScoringConfig:
    return ScoringConfig.from_dict(load_yaml("scoring.yaml"))


def load_pillars() -> dict[str, dict]:
    return load_yaml("pillars.yaml")
