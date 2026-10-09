"""User actions on stories (PRD section 24).

Every action is stored as a row. The current state of a toggle (liked, saved, hidden topic, ...) is the latest
row for that item, so history is kept for engagement metrics while the app shows the present choice.
"""

from dataclasses import dataclass, field

# action -> (family, turns_on). Actions in one family toggle the same item.
_TOGGLES = {
    "like": ("reaction", "like"), "dislike": ("reaction", "dislike"),
    "unlike": ("reaction", None), "undislike": ("reaction", None),
    "save": ("save", True), "unsave": ("save", False),
    "hide_topic": ("hide_topic", True), "unhide_topic": ("hide_topic", False),
    "follow_topic": ("follow_topic", True), "unfollow_topic": ("follow_topic", False),
    "follow_source": ("follow_source", True), "unfollow_source": ("follow_source", False),
}
EVENTS = {"share", "open_source", "read"}
ACTIONS = set(_TOGGLES) | EVENTS


@dataclass
class UserState:
    liked: set[int] = field(default_factory=set)
    disliked: set[int] = field(default_factory=set)
    saved: list[int] = field(default_factory=list)  # most recently saved first
    hidden_pillars: set[str] = field(default_factory=set)
    followed_pillars: set[str] = field(default_factory=set)
    followed_sources: set[str] = field(default_factory=set)


def state_from_rows(rows: list[tuple[str, int | None, str | None]]) -> UserState:
    """Rows of (action, story_id, value) in chronological order -> current state."""
    latest: dict[tuple[str, object], object] = {}
    saved_order: list[int] = []
    for action, story_id, value in rows:
        if action not in _TOGGLES:
            continue
        family, on = _TOGGLES[action]
        key = (family, story_id if family in ("reaction", "save") else value)
        latest[key] = on
        if family == "save" and on and story_id is not None:
            if story_id in saved_order:
                saved_order.remove(story_id)
            saved_order.insert(0, story_id)

    s = UserState()
    for (family, item), on in latest.items():
        if family == "reaction":
            if on == "like":
                s.liked.add(item)
            elif on == "dislike":
                s.disliked.add(item)
        elif on:
            {"hide_topic": s.hidden_pillars, "follow_topic": s.followed_pillars,
             "follow_source": s.followed_sources}.get(family, set()).add(item)
    s.saved = [sid for sid in saved_order if latest.get(("save", sid))]
    return s


def record(conn, user_id: str, action: str, story_id: int | None = None, value: str | None = None) -> None:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    conn.run(
        "insert into feedback (user_id, story_id, action, value) values (cast(:u as uuid), :s, :a, :v)",
        u=user_id, s=story_id, a=action, v=value,
    )


def load_state(conn, user_id: str) -> UserState:
    rows = conn.run(
        """select action, story_id, value from feedback
           where user_id = cast(:u as uuid) and action <> all(cast(:events as text[]))
           order by created_at, id""",
        u=user_id, events=sorted(EVENTS),
    )
    return state_from_rows([tuple(r) for r in rows])


def pillar_reactions(conn, user_id: str) -> dict[str, int]:
    """Net current likes minus dislikes per pillar (the latest reaction per story counts)."""
    rows = conn.run(
        """select s.pillar, sum(case r.action when 'like' then 1 when 'dislike' then -1 else 0 end)
           from (select distinct on (story_id) story_id, action from feedback
                 where user_id = cast(:u as uuid) and action in ('like', 'unlike', 'dislike', 'undislike')
                 order by story_id, created_at desc, id desc) r
           join stories s on s.id = r.story_id
           group by s.pillar""",
        u=user_id,
    )
    return {r[0]: int(r[1]) for r in rows if r[0]}
