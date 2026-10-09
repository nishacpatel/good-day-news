"""Explore and search constructive news (PRD sections 8.3 and 22)."""

from datetime import date, timedelta

import streamlit as st

from gooddaynews.briefing.store import load_signals, stories_by_id
from gooddaynews.explore import SORTS, browse, search
from gooddaynews.rag.models import Filters
from gooddaynews.ui.common import configs, current_profile, db, llm
from gooddaynews.ui.components import story_card, user_state

GEOGRAPHY = {"Anywhere": [], "India": ["IN"], "Global / international": ["INT"]}
DATES = {"Any time": None, "Today": 0, "Last 7 days": 7, "Last 30 days": 30}
SEARCH_EXAMPLES = "positive AI news · climate solutions India · good news Mumbai · scientific breakthroughs this month"


def filters_row(pillars: dict) -> tuple[Filters, str]:
    labels = {p["label"]: key for key, p in pillars.items()}
    c1, c2, c3, c4 = st.columns(4)
    chosen = c1.multiselect("Category", list(labels), placeholder="All")
    where = c2.selectbox("Geography", list(GEOGRAPHY))
    when = c3.selectbox("Published", list(DATES))
    sort_options = list(SORTS) if current_profile() else [k for k in SORTS if k != "for_you"]
    sort = c4.selectbox("Sort by", sort_options, format_func=SORTS.get)
    days = DATES[when]
    start = date.today() - timedelta(days=days) if days is not None else None
    return Filters(pillars=[labels[c] for c in chosen], countries=GEOGRAPHY[where], start=start), sort


def explore_tab() -> None:
    pillars, briefing_cfg, _ = configs()
    query = st.text_input("Search", placeholder="Search constructive news", label_visibility="collapsed")
    st.caption(f"Try: {SEARCH_EXAMPLES}")
    f, sort = filters_row(pillars)
    profile, state = current_profile(), user_state()
    with st.spinner("Searching…" if query else "Loading stories…"):
        with db() as conn:
            if query.strip():
                stories = search(conn, llm(), query, f, limit=20, hidden=state.hidden_pillars)
            else:
                signals = load_signals(conn, profile.id) if profile else None
                stories = browse(conn, f, sort, limit=20, hidden=state.hidden_pillars, profile=profile,
                                 cfg=briefing_cfg, signals=signals)
    if not stories:
        if query.strip():
            st.info("No stories match that search. Try fewer words, another category, or a wider date range. "
                    "This app only covers constructive news, so some topics won't appear.")
        else:
            st.info("No stories match these filters. Try a wider date range or another category.")
        return
    st.caption(f"{len(stories)} {'result' if len(stories) == 1 else 'stories'}"
               + (f" · {len(state.hidden_pillars)} hidden topic(s) left out" if state.hidden_pillars else ""))
    for s in stories:
        story_card(s, key=f"e{s.id}", show_why=False)


def saved_tab() -> None:
    profile, state = current_profile(), user_state()
    if profile is None:
        st.info("Sign in on My preferences to save stories for later.")
        return
    if not state.saved:
        st.info("Stories you save appear here. Use 🔖 Save on any story.")
        return
    with db() as conn:
        stories = stories_by_id(conn, state.saved)
    for s in stories:
        story_card(s, key=f"s{s.id}", show_why=False)


def page() -> None:
    st.markdown("## Explore")
    explore, saved = st.tabs(["Explore", f"Saved ({len(user_state().saved)})"])
    with explore:
        explore_tab()
    with saved:
        saved_tab()
