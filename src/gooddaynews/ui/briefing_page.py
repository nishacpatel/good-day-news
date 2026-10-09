"""Today's Briefing (PRD sections 8.1 and 16)."""

import streamlit as st

from gooddaynews.briefing.models import Briefing, BriefingStory
from gooddaynews.briefing.service import get_briefing
from gooddaynews.ui import nav
from gooddaynews.ui.common import (configs, current_profile, db, llm, pillar_label, place_text,
                                   verification_short)


def story_card(i: int, s: BriefingStory) -> None:
    with st.container(border=True):
        st.caption(f"{pillar_label(s.pillar).upper()}" + (f" · {s.subcategory}" if s.subcategory else ""))
        st.markdown(f"#### {s.headline}")
        st.write(s.summary)
        if s.why_it_matters:
            st.markdown(f"**Why it matters:** {s.why_it_matters}")
        when = s.published_at.strftime("%d %b %Y") if s.published_at else "Date unknown"
        source = s.sources[0][0] if s.sources else "Unknown source"
        st.caption(f"{place_text(s.place, s.country)} · {when} · {source} · "
                   f"{verification_short(s.verification_level, s.source_count)}")
        cols = st.columns([1, 1, 2])
        if s.sources:
            cols[0].link_button("Read more", s.sources[0][1], use_container_width=True)
        if cols[1].button("Ask AI", key=f"ask-{s.id}", use_container_width=True):
            st.session_state.story_in_view = {"id": s.id, "headline": s.headline}
            nav.go("chat")


def show(b: Briefing, name: str | None) -> None:
    st.markdown(f"## ☀️ Good morning{', ' + name if name else ''}.")
    st.markdown(f"### {b.title[0].upper()}{b.title[1:]}")
    st.caption(b.for_date.strftime("%A, %d %B %Y"))
    if b.is_fallback:
        st.info(f"Today's briefing isn't ready yet, so here is your briefing from {b.for_date:%d %B}.")
    elif b.window_hours > 24:
        st.caption(f"There wasn't much new in the last day, so this includes stories from the last "
                   f"{b.window_hours // 24} days.")
    for i, s in enumerate(b.stories, 1):
        story_card(i, s)
    if b.thought:
        st.markdown("#### Something to think about today")
        st.markdown(f"> {b.thought}")
    st.caption("This briefing complements, not replaces, regular news. Every story links to its original source.")


def page() -> None:
    profile = current_profile()
    if profile is None:
        st.markdown("## ☀️ Start your day with what went right.")
        st.write("Get a short daily briefing of meaningful progress from credible sources, chosen for your interests.")
        nav.link("profile", "Set up your briefing", "✨")
        return

    _, briefing_cfg, scoring = configs()
    rebuild = st.session_state.pop("rebuild_briefing", False)
    key = ("briefing", profile.id, str(profile.local_date()))
    if rebuild or key not in st.session_state:
        with st.spinner("Preparing your briefing…"):
            try:
                with db() as conn:
                    st.session_state[key] = get_briefing(conn, llm(), profile, briefing_cfg, scoring, rebuild=rebuild)
            except Exception as exc:
                st.error("Your briefing couldn't be loaded right now. Please try again in a moment.")
                st.caption(f"{type(exc).__name__}: {str(exc)[:200]}")
                return
    briefing = st.session_state[key]
    if briefing is None or not briefing.stories:
        st.info("There are no new stories yet. Check back later today.")
        return
    show(briefing, profile.display_name)
    if st.button("Refresh my briefing"):
        st.session_state.rebuild_briefing = True
        st.rerun()
