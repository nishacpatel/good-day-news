"""Database access for profiles and briefings."""

from datetime import date, time

from gooddaynews.briefing.models import Briefing, BriefingStory, Profile

_PROFILE_COLUMNS = ("id::text, email, display_name, topics, geography, briefing_length, notify_time, timezone, "
                    "notify_enabled")


def _profile(row) -> Profile:
    return Profile(id=row[0], email=row[1], display_name=row[2], topics=list(row[3] or []),
                   geography=list(row[4] or []), briefing_length=row[5], notify_time=row[6],
                   timezone=row[7], notify_enabled=row[8])


def get_profile(conn, email: str) -> Profile | None:
    rows = conn.run(f"select {_PROFILE_COLUMNS} from user_profiles where email = :email", email=email.strip().lower())
    return _profile(rows[0]) if rows else None


def save_profile(conn, email: str, display_name: str | None, topics: list[str], geography: list[str],
                 briefing_length: str, notify_time: time, timezone: str, notify_enabled: bool) -> Profile:
    rows = conn.run(
        f"""insert into user_profiles (email, display_name, topics, geography, briefing_length, notify_time, timezone,
                                       notify_enabled)
            values (:email, :name, cast(:topics as text[]), cast(:geo as text[]), :length, :notify_time, :tz, :notify)
            on conflict (email) do update set
                display_name = excluded.display_name, topics = excluded.topics, geography = excluded.geography,
                briefing_length = excluded.briefing_length, notify_time = excluded.notify_time,
                timezone = excluded.timezone, notify_enabled = excluded.notify_enabled
            returning {_PROFILE_COLUMNS}""",
        email=email.strip().lower(), name=display_name or None, topics=topics, geo=geography,
        length=briefing_length, notify_time=notify_time, tz=timezone, notify=notify_enabled,
    )
    return _profile(rows[0])


def all_profiles(conn) -> list[Profile]:
    return [_profile(r) for r in conn.run(f"select {_PROFILE_COLUMNS} from user_profiles")]


_STORY_COLUMNS = """id, headline, coalesce(summary, ''), coalesce(why_it_matters, ''), coalesce(pillar, ''), subcategory,
                    country, place, coalesce(published_at, created_at), coalesce(score, 0),
                    coalesce(verification_level, ''), source_count"""


def _stories_with_sources(conn, rows) -> list[BriefingStory]:
    stories = {
        r[0]: BriefingStory(id=r[0], headline=r[1], summary=r[2], why_it_matters=r[3], pillar=r[4], subcategory=r[5],
                            country=r[6], place=r[7], published_at=r[8], score=float(r[9]),
                            verification_level=r[10], source_count=r[11])
        for r in rows
    }
    if stories:
        for story_id, name, url in conn.run(
            """select a.story_id, s.name, a.url from articles a join sources s on s.id = a.source_id
               where a.story_id = any(cast(:ids as bigint[])) order by s.credibility desc, a.published_at""",
            ids=list(stories),
        ):
            stories[story_id].sources.append((name, url))
    return list(stories.values())


def recent_stories(conn, hours: int) -> list[BriefingStory]:
    rows = conn.run(
        f"""select {_STORY_COLUMNS} from stories
            where status = 'published' and coalesce(published_at, created_at) > now() - make_interval(hours => :hours)""",
        hours=hours,
    )
    return _stories_with_sources(conn, rows)


def stories_by_id(conn, ids: list[int]) -> list[BriefingStory]:
    if not ids:
        return []
    rows = conn.run(
        f"select {_STORY_COLUMNS} from stories where id = any(cast(:ids as bigint[])) and status = 'published'",
        ids=ids,
    )
    found = {s.id: s for s in _stories_with_sources(conn, rows)}
    return [found[i] for i in ids if i in found]  # keep the briefing's order


def pillar_feedback(conn, user_id: str) -> dict[str, int]:
    """Net likes minus dislikes per pillar for this user."""
    rows = conn.run(
        """select s.pillar, sum(case f.action when 'like' then 1 when 'dislike' then -1 else 0 end)
           from feedback f join stories s on s.id = f.story_id
           where f.user_id = cast(:uid as uuid) and f.action in ('like', 'dislike')
           group by s.pillar""",
        uid=user_id,
    )
    return {r[0]: int(r[1]) for r in rows if r[0]}


def save_briefing(conn, b: Briefing) -> None:
    conn.run(
        """insert into briefings (user_id, for_date, story_ids, intro, thought, window_hours)
           values (cast(:uid as uuid), :d, cast(:ids as bigint[]), :intro, :thought, :window)
           on conflict (user_id, for_date) do update set
               story_ids = excluded.story_ids, intro = excluded.intro, thought = excluded.thought,
               window_hours = excluded.window_hours, created_at = now()""",
        uid=b.user_id, d=b.for_date, ids=[s.id for s in b.stories], intro=b.title, thought=b.thought,
        window=b.window_hours,
    )


def load_briefing(conn, user_id: str, on_or_before: date) -> Briefing | None:
    """The user's briefing for a date, or their most recent earlier one."""
    rows = conn.run(
        """select for_date, story_ids, intro, thought, window_hours from briefings
           where user_id = cast(:uid as uuid) and for_date <= :d order by for_date desc limit 1""",
        uid=user_id, d=on_or_before,
    )
    if not rows:
        return None
    for_date, ids, title, thought, window = rows[0]
    return Briefing(user_id, for_date, stories_by_id(conn, list(ids)), title, thought, window,
                    is_fallback=for_date != on_or_before)
