"""Story card and story actions shared by the briefing, Explore and story pages (PRD sections 23, 24, 27)."""

import streamlit as st

from gooddaynews import feedback
from gooddaynews.briefing.models import BriefingStory
from gooddaynews.notify.messages import first_sentence, story_url
from gooddaynews.settings import get_settings
from gooddaynews.ui import nav
from gooddaynews.ui.common import current_profile, db, pillar_label, place_text, verification_short


def user_state() -> feedback.UserState:
    """The signed-in user's likes, saves and follows, loaded once per session and refreshed after each action."""
    profile = current_profile()
    if profile is None:
        return feedback.UserState()
    if "user_state" not in st.session_state:
        with db() as conn:
            st.session_state.user_state = feedback.load_state(conn, profile.id)
    return st.session_state.user_state


def act(action: str, story_id: int | None = None, value: str | None = None, rerun: bool = True) -> None:
    profile = current_profile()
    if profile is None:
        st.toast("Sign in on My preferences to like, save and follow stories.")
        return
    with db() as conn:
        feedback.record(conn, profile.id, action, story_id, value)
        st.session_state.user_state = feedback.load_state(conn, profile.id)
    if rerun:
        st.rerun()


def share_text(s: BriefingStory) -> str:
    """Headline, short summary, source, branding and a link back: never the article itself (PRD 27)."""
    source = s.sources[0][0] if s.sources else "the original source"
    return (f"{s.headline}\n{first_sentence(s.summary)}\nSource: {source}\n"
            f"Shared from Constructive News AI: {story_url(get_settings().app_url, s.id)}")


def story_actions(s: BriefingStory, key: str, show_details: bool = True) -> None:
    state = user_state()
    liked, disliked, saved = s.id in state.liked, s.id in state.disliked, s.id in state.saved
    # A horizontal container wraps on phones; st.columns would stack every button on its own row.
    row = st.container(horizontal=True, wrap=True, gap="small")
    if row.button("👍", key=f"like-{key}", type="primary" if liked else "secondary", help="More like this"):
        act("unlike" if liked else "like", s.id)
    if row.button("👎", key=f"dislike-{key}", type="primary" if disliked else "secondary", help="Less like this"):
        act("undislike" if disliked else "dislike", s.id)
    if row.button("Saved" if saved else "Save", key=f"save-{key}", icon="🔖",
                  type="primary" if saved else "secondary"):
        act("unsave" if saved else "save", s.id)
    def on_share_toggle():
        if st.session_state.get(f"share-{key}"):  # count opening, not closing
            act("share", s.id, rerun=False)

    with row.popover("Share", icon="↗", on_change=on_share_toggle, key=f"share-{key}"):
        st.caption("Copy this to share the story:")
        st.code(share_text(s), language=None, wrap_lines=True)
    with row.popover("More", key=f"more-{key}"):
        topic, domain = pillar_label(s.pillar), s.sources[0][2] if s.sources else None
        hidden, followed = s.pillar in state.hidden_pillars, s.pillar in state.followed_pillars
        if st.button(f"{'Show' if hidden else 'Hide'} {topic} stories", key=f"hide-{key}"):
            act("unhide_topic" if hidden else "hide_topic", value=s.pillar)
        if st.button(f"{'Unfollow' if followed else 'Follow'} {topic}", key=f"follow-{key}"):
            act("unfollow_topic" if followed else "follow_topic", value=s.pillar)
        if domain:
            following_source = domain in state.followed_sources
            if st.button(f"{'Unfollow' if following_source else 'Follow'} {s.sources[0][0]}", key=f"src-{key}"):
                act("unfollow_source" if following_source else "follow_source", value=domain)
    if row.button("Ask AI", key=f"ask-{key}", icon="💬"):
        st.session_state.story_in_view = {"id": s.id, "headline": s.headline}
        nav.go("chat")
    links = []
    if s.sources:
        links.append(f"[Read the original ↗]({s.sources[0][1]})")
    st.markdown(" · ".join(links))
    if show_details:
        nav.link("story", "Story details, key facts and related stories", id=s.id)


def story_card(s: BriefingStory, key: str, show_why: bool = True) -> None:
    with st.container(border=True):
        st.caption(pillar_label(s.pillar).upper() + (f" · {s.subcategory}" if s.subcategory else ""))
        st.markdown(f"#### {s.headline}")
        st.write(s.summary)
        if show_why and s.why_it_matters:
            st.markdown(f"**Why it matters:** {s.why_it_matters}")
        when = s.published_at.strftime("%d %b %Y") if s.published_at else "Date unknown"
        source = s.sources[0][0] if s.sources else "Unknown source"
        st.caption(f"{place_text(s.place, s.country)} · {when} · {source} · "
                   f"{verification_short(s.verification_level, s.source_count)}")
        story_actions(s, key)
