"""Shapes of the structured answers we ask the LLM for."""

from typing import Literal

from pydantic import BaseModel, Field


class TriageItem(BaseModel):
    id: int
    candidate: bool = Field(description="true if the item might report constructive news")
    reason: str = Field(description="a few words explaining the decision")


class TriageResult(BaseModel):
    items: list[TriageItem]


class DimensionScores(BaseModel):
    constructive_impact: int = Field(description="0-10: how much real positive change the event represents")
    significance: int = Field(description="0-10: how meaningful the development is beyond a small circle")
    human_impact: int = Field(description="0-10: how much it improves or affects people's lives")
    novelty: int = Field(description="0-10: how genuinely new or noteworthy it is")
    evidence_quality: int = Field(description="0-10: how well the claims are supported by data, research or official records")
    emotional_value: int = Field(description="0-10: hope, inspiration, wonder, gratitude or curiosity it can evoke")


class StoryAssessment(BaseModel):
    constructive: bool = Field(description="true only if the underlying event is meaningful progress, not just positive wording")
    reject_reason: str = Field(description="why it is not constructive; empty string when constructive is true")
    is_opinion: bool = Field(description="true for opinion, commentary, editorials, reviews or promotional pieces")
    evidence_basis: Literal["research", "official_data", "primary_announcement", "news_reporting"]
    pillar: str = Field(description="one pillar key from the list provided")
    subcategory: str = Field(description="one subcategory of that pillar")
    country: str = Field(description="ISO 3166-1 alpha-2 code of the main country, 'INT' if global, '' if unknown")
    place: str = Field(description="city, state or region if stated, else ''")
    entities: list[str] = Field(description="up to 8 organisations, people or places central to the story")
    scores: DimensionScores
    headline: str = Field(description="factual, neutral headline under 14 words; no hype or clickbait")
    summary: str = Field(description="2-4 sentence factual summary using only facts stated in the article")
    why_it_matters: str = Field(description="1-2 sentences on who benefits and why it is significant")
    key_facts: list[str] = Field(description="3-5 short facts, each stated explicitly in the article text")
