"""Prompts for interpreting questions and writing grounded answers (PRD sections 19-20)."""

from datetime import date

from gooddaynews.rag.models import Passage, StoryHit, Turn

VERIFICATION_TEXT = {
    "multiple_sources": "reported by {n} independent sources",
    "primary_source": "from the primary source (the organisation itself)",
    "research": "based on published research, one report",
    "official_data": "based on official data, one report",
    "single_source": "reported by one source",
    "opinion": "opinion or commentary",
}


def verification_text(story: StoryHit) -> str:
    return VERIFICATION_TEXT.get(story.verification_level, "reported by one source").format(n=story.source_count)


INTERPRET_SYSTEM = """You turn a user's message to a constructive-news assistant into a search plan.

- standalone_question: rewrite follow-ups ("tell me more", "are there other examples?") so they make sense alone,
  using the conversation and the story in view.
- intent: news_search (find news), story_followup (more about stories already discussed or the story in view),
  verification ("is this verified?", "what is the source?", "how reliable is this?"), personal ("which would
  interest me?"), out_of_scope (not about news: recipes, coding, homework, chit-chat, requests to write content).
- broad: true only when the user wants an overview without a specific topic, e.g. "what good happened today?".
- Dates: convert relative times using today's date. "today" = today; "yesterday" = yesterday;
  "this week" = the last 7 days; "this month" = the last 30 days. Leave both dates '' if no time is mentioned.
- pillars and countries: only when the user clearly limits the question to them."""


def interpret_prompt(message: str, today: date, history: list[Turn], pillars: dict, story_in_view: str | None) -> str:
    convo = "\n".join(f"{t.role}: {t.text[:400]}" for t in history) or "(none)"
    pillar_list = ", ".join(f"{k} ({p['label']})" for k, p in pillars.items())
    return f"""Today's date: {today.isoformat()}
Pillar keys: {pillar_list}
Story in view: {story_in_view or '(none)'}

Conversation so far:
{convo}

User message: {message}"""


ANSWER_SYSTEM = """You are the assistant in a constructive-news app. You answer questions using ONLY the numbered
news sources provided. Today's date is given with the sources.

Rules:
1. Every factual statement must come from the sources and end with its citation, like [1] or [2][3].
2. Never invent news, numbers, quotes, sources or dates. Never present rumours or early research as settled fact.
   Never change facts to make a story sound more positive than the sources say.
3. Give dates for events ("on 7 October", "this week") so the reader knows how recent the news is.
4. Use your own words. Quote directly at most once, under 15 words, in quotation marks.
5. If the sources do not answer the question, reply with exactly this sentence and nothing else:
   "{refusal}"
   If they answer only part of it, answer that part and say plainly what the sources do not cover.
6. For "is this verified?" or "how reliable is this?", state the Verification line given for the story in its own
   words (for example "reported by one source"), then what the reporting is based on (research, official data,
   named organisations). Do not call a source "primary" unless its Verification line says so. Do not invent a
   confidence percentage. If only one outlet reported it, say that other outlets in this collection have not
   confirmed it.
7. For "which would interest me?", use the user's topics if given.
8. Be clear and concise: usually 60-180 words. Use a short list when covering several stories.
   If asked to explain simply, use plain language a teenager would follow."""


def story_block(n: int, s: StoryHit, passages: list[Passage]) -> str:
    when = s.published_at.strftime("%d %b %Y") if s.published_at else "date unknown"
    where = ", ".join(x for x in (s.place, s.country) if x) or "location not stated"
    names = "; ".join(dict.fromkeys(src.name for src in s.sources)) or "unknown"
    facts = "\n".join(f"  - {f}" for f in s.key_facts) or "  - (none)"
    text = "\n".join(f'  "{p.text.strip()}"' for p in passages) or "  (no full-text passages available)"
    return f"""[{n}] {s.headline}
Published: {when} | Where: {where} | Pillar: {s.pillar}
Sources: {names}
Verification: {verification_text(s)}
Summary: {s.summary}
Why it matters: {s.why_it_matters}
Key facts:
{facts}
Passages from the original reporting:
{text}"""


def answer_prompt(question: str, today: date, stories: list[StoryHit], passages: list[Passage],
                  history: list[Turn], user_topics: list[str] | None) -> str:
    blocks = "\n\n".join(
        story_block(i, s, [p for p in passages if p.story_id == s.id]) for i, s in enumerate(stories, 1)
    )
    convo = "\n".join(f"{t.role}: {t.text[:600]}" for t in history) or "(none)"
    topics = ", ".join(user_topics) if user_topics else "(not set)"
    return f"""Today's date: {today.isoformat()}
User's topics: {topics}

Sources:
{blocks}

Conversation so far:
{convo}

Question: {question}"""
