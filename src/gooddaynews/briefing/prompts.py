"""Prompt for the briefing's closing line, "Something to think about today" (PRD section 16)."""

from pydantic import BaseModel, Field

from gooddaynews.briefing.models import BriefingStory


class Thought(BaseModel):
    thought: str = Field(description="1-2 sentences, under 45 words")


THOUGHT_SYSTEM = """You write the closing line of a morning news briefing, titled "Something to think about today".

Write one short, thoughtful observation (1-2 sentences, under 45 words) that connects some of today's stories.
Rules:
- Use only what the stories say. Do not add facts, numbers, names or claims that are not in them.
- Be warm but grounded: no clichés ("faith in humanity restored"), no exclamation marks, no overstatement,
  and do not imply that the world's problems are solved.
- Do not give advice or instructions to the reader."""


def thought_prompt(stories: list[BriefingStory]) -> str:
    lines = "\n".join(f"- {s.headline}: {s.why_it_matters}" for s in stories)
    return f"Today's stories:\n{lines}"
