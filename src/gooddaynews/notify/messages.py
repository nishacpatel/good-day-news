"""Notification wording and the briefing email (PRD sections 21 and 27). No sending here."""

import html
import re
from dataclasses import dataclass
from datetime import date, datetime

from gooddaynews.briefing.models import Briefing, Profile

# Story-specific openers from PRD 21, used on alternate days so notifications don't feel repetitive.
PILLAR_SUBJECTS = {
    "environment": "🌱 A conservation success story worth knowing today.",
    "science": "🔬 Today's science story may surprise you.",
}
COMMUNITY_SUBJECT = "❤️ Something wonderful happened in your community."
WEEKDAYS = {"daily": range(7), "weekdays": range(5), "weekends": range(5, 7)}


@dataclass
class Message:
    subject: str
    text: str
    html: str


def first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return match.group(1) if match else text.strip()


def subject_for(b: Briefing, profile: Profile, home_countries: set[str]) -> str:
    n = len(b.stories)
    base = f"☀️ Good morning. {n} thing{'s' if n != 1 else ''} went right in the world yesterday."
    if b.for_date.toordinal() % 2 == 0 or not b.stories:
        return base
    top = b.stories[0]
    if top.pillar in ("humanity", "people") and top.country in home_countries:
        return COMMUNITY_SUBJECT
    return PILLAR_SUBJECTS.get(top.pillar, base)


def is_due(profile: Profile, local_now: datetime, already_sent: bool) -> bool:
    return (profile.notify_enabled and not already_sent
            and local_now.weekday() in WEEKDAYS.get(profile.frequency, WEEKDAYS["daily"])
            and local_now.time() >= profile.notify_time)


def story_url(app_url: str, story_id: int) -> str:
    return f"{app_url.rstrip('/')}/story?id={story_id}"


def briefing_email(b: Briefing, profile: Profile, app_url: str, home_countries: set[str]) -> Message:
    """Headlines, one line each, and links back to the app. Never the article text (copyright)."""
    subject = subject_for(b, profile, home_countries)
    greeting = f"Good morning{', ' + profile.display_name if profile.display_name else ''}."
    title = b.title[0].upper() + b.title[1:]
    prefs = f"{app_url.rstrip('/')}/preferences"

    lines = [greeting, title, ""]
    items = []
    for i, s in enumerate(b.stories, 1):
        source = s.sources[0][0] if s.sources else "source"
        url = story_url(app_url, s.id)
        lines += [f"{i}. {s.headline}", f"   {first_sentence(s.summary)}", f"   {source} · {url}", ""]
        items.append(
            f'<li style="margin-bottom:14px"><a href="{html.escape(url)}" style="color:#0a6c69;font-weight:600;'
            f'text-decoration:none">{html.escape(s.headline)}</a><br><span style="color:#333">'
            f'{html.escape(first_sentence(s.summary))}</span><br><span style="color:#777;font-size:12px">'
            f'{html.escape(source)}</span></li>'
        )
    if b.thought:
        lines += ["Something to think about today:", b.thought, ""]
    footer = (f"You get this because daily notifications are on. Change the time, frequency or turn them off: {prefs}")
    lines.append(footer)

    thought_html = (f'<p style="margin-top:20px;color:#555"><em>Something to think about today</em><br>'
                    f'{html.escape(b.thought)}</p>') if b.thought else ""
    body = f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;margin:auto;color:#18212b">
<p style="font-size:18px">☀️ {html.escape(greeting)}</p>
<h2 style="font-size:20px;margin:0 0 16px">{html.escape(title)}</h2>
<ol style="padding-left:20px">{''.join(items)}</ol>{thought_html}
<p style="color:#888;font-size:12px;margin-top:24px">Constructive News AI · You get this because daily notifications
are on. <a href="{html.escape(prefs)}">Change or turn off notifications</a>.</p></div>"""
    return Message(subject, "\n".join(lines), body)


def due_today(d: date, frequency: str) -> bool:
    return d.weekday() in WEEKDAYS.get(frequency, WEEKDAYS["daily"])
