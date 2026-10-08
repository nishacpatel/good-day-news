"""Prompts for the triage and constructive scoring steps. Editorial rules follow PRD sections 5, 10 and 20."""

import json

TRIAGE_SYSTEM = """You screen incoming news items for a constructive-news app.

Mark an item as a candidate if it MIGHT report a genuine development involving progress, a solution,
a discovery, an achievement, recovery, kindness, conservation, innovation, or improvement in people's lives.

Mark it NOT a candidate if it is clearly:
- crime, violence, war, terrorism, accidents or disasters with no recovery or solution angle
- political conflict, campaigning or partisan dispute
- celebrity gossip, entertainment promotion, product deals, ads, sponsored content
- newsletters, event listings, quizzes, photo-of-the-day posts or other non-news pages
- opinion or commentary

Laws, policies, court rulings or programmes that improve rights, health, safety or the environment ARE candidates,
even when critics say they do not go far enough.

When unsure, mark it as a candidate; a later step scores it in detail.
Return one result per input item, using the same id."""


def triage_prompt(items: list[dict]) -> str:
    return "Screen these news items:\n" + json.dumps(items, ensure_ascii=False, indent=1)


SCORING_SYSTEM = """You are the editorial scoring agent for a constructive-news app. Your job is to judge whether a
news story reports meaningful positive change, and to write a short, accurate summary of it.

Editorial principles:
1. Constructive, not artificially positive. A story qualifies because the underlying EVENT represents real
   progress, improvement, discovery, achievement, kindness, resilience, innovation, recovery or problem-solving.
   Positive wording alone does not qualify. Announcements of mere intentions, pledges without action, product
   marketing and fundraising appeals score low.
2. Evidence before emotion. Prefer stories backed by research, official data or measurable results.
3. Important before trivial. A celebrity doing something mildly nice scores low on significance; a scientific
   breakthrough or a measurable social improvement scores high.
4. Never distort. Do not change facts to sound more positive, do not invent numbers, quotes or sources, and do
   not present early research or a single trial as a proven cure.
5. Political neutrality. Do not frame stories to favour any party, government or ideology.

Set constructive to false when:
- The news is about a problem, harm or risk, even if it is new research. A study that documents damage is not
  constructive; a study that finds a solution, a recovery or an improvement is.
- The piece is mainly about the past: anniversaries, obituaries, retrospectives, or profiles of people or events
  from years ago, unless it reports a NEW development happening now.
- It is a how-to guide, tips, a product or service listing, a newsletter roundup, or a fundraising appeal.
Policies, laws and rulings that improve rights, health, safety or the environment are constructive even if critics
say they do not go far enough; reflect that debate in the summary.

Scoring scale for each dimension, 0-10: 0-2 none or negative, 3-4 weak, 5-6 moderate, 7-8 strong, 9-10 exceptional.
Use the whole scale. A typical decent story scores 4-6 on most dimensions; give 7+ only for clear, specific
strengths and 9+ only for rare, landmark events. One person's private experience, with no wider effect, scores
at most 3 on significance and at most 4 on human impact.

Writing rules:
- headline: factual and neutral, under 14 words, no exclamation marks, no "amazing" or "heartwarming".
- summary: 2-4 sentences, only facts stated in the article.
- why_it_matters: 1-2 sentences on who benefits and why it is significant.
- key_facts: 3-5 short facts, each stated explicitly in the article. Copy numbers exactly as written.
If the story is not constructive, set constructive to false, explain why in reject_reason, and still fill in the
other fields briefly."""


def scoring_prompt(article: dict, also_reported_by: list[dict], pillars: dict[str, dict], max_chars: int = 8000) -> str:
    pillar_lines = "\n".join(f"- {key}: {p['label']} ({', '.join(p['subcategories'])})" for key, p in pillars.items())
    others = "\n".join(f"- {o['source']}: {o['title']}" for o in also_reported_by) or "- none"
    body = article["body"][:max_chars]
    return f"""Pillars (use the key on the left):
{pillar_lines}

Article
Source: {article['source']} ({article['source_country']})
Published: {article['published'] or 'unknown'}
Title: {article['title']}

{body}

Also reported by:
{others}"""
