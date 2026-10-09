"""Sign in and briefing preferences (PRD sections 5.5, 18 and 39)."""

from datetime import time

import streamlit as st

from gooddaynews.briefing import store
from gooddaynews.briefing.models import LENGTHS
from gooddaynews.ui import nav
from gooddaynews.ui.common import configs, current_profile, db, pillar_label
from gooddaynews.ui.components import act, user_state

LENGTH_LABELS = {"quick": "Quick: 2–3 stories, about 2 minutes", "standard": "Standard: 5–7 stories, about 5 minutes",
                 "deep": "Deep: 8–12 stories, about 10 minutes"}
FREQUENCIES = {"daily": "Every day", "weekdays": "Weekdays only", "weekends": "Weekends only"}
TIMEZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York",
             "America/Los_Angeles", "Australia/Sydney", "UTC"]


def sign_in() -> None:
    st.markdown("## Sign in")
    st.caption("Demo sign-in: enter your email to load or create your preferences. "
               "Password sign-in will replace this before launch.")
    with st.form("sign-in"):
        email = st.text_input("Email", placeholder="you@example.com")
        if st.form_submit_button("Continue", type="primary"):
            email = email.strip().lower()
            if "@" not in email or "." not in email.split("@")[-1]:
                st.error("Enter a valid email address, like you@example.com.")
                return
            with db() as conn:
                profile = store.get_profile(conn, email)
            st.session_state.profile = profile
            st.session_state.pending_email = None if profile else email
            st.session_state.pop("user_state", None)  # don't carry another person's likes and saves
            st.rerun()


def preferences(email: str) -> None:
    _, briefing_cfg, _ = configs()
    profile = current_profile()
    st.markdown("## Your briefing")
    st.caption(f"Signed in as {email}")
    with st.form("preferences"):
        name = st.text_input("What should we call you? (optional)", value=(profile.display_name if profile else "") or "")
        topics = st.multiselect("Topics you care about", list(briefing_cfg.topics),
                                default=profile.topics if profile else ["Science", "Environment", "Humanity"])
        geography = st.multiselect("Where", list(briefing_cfg.geography),
                                   default=profile.geography if profile else ["India", "Global"])
        length = st.radio("Briefing length", LENGTHS, format_func=LENGTH_LABELS.get,
                          index=LENGTHS.index(profile.briefing_length) if profile else 1)
        c1, c2 = st.columns(2)
        notify_time = c1.time_input("Briefing time", value=profile.notify_time if profile else time(6, 0), step=1800)
        tz = c2.selectbox("Time zone", TIMEZONES,
                          index=TIMEZONES.index(profile.timezone) if profile and profile.timezone in TIMEZONES else 0)
        c3, c4 = st.columns(2)
        notify = c3.toggle("Notification email", value=profile.notify_enabled if profile else True)
        frequency = c4.selectbox("How often", list(FREQUENCIES), format_func=FREQUENCIES.get,
                                 index=list(FREQUENCIES).index(profile.frequency) if profile else 0)
        if st.form_submit_button("Save", type="primary"):
            if not topics:
                st.error("Choose at least one topic.")
                return
            with db() as conn:
                st.session_state.profile = store.save_profile(conn, email, name.strip(), topics, geography, length,
                                                              notify_time, tz, notify, frequency)
            st.session_state.pending_email = None
            st.session_state.rebuild_briefing = True
            nav.go("briefing")

    if profile:
        follows_and_hides()

    with st.expander("What we store and why"):
        st.write("Your email, name (optional), topics, places, briefing length and notification settings, used only "
                 "to choose your stories and send your briefing. Likes, saves and follows are stored to improve your "
                 "briefing. Chat messages are kept only for the current session and are not saved. Location is "
                 "stored as a region, never as an exact place.")
    if profile and st.button("Sign out"):
        for k in ("profile", "pending_email", "chat", "messages", "story_in_view", "user_state"):
            st.session_state.pop(k, None)
        st.rerun()


def follows_and_hides() -> None:
    """Undo follows and hidden topics set from story cards (PRD 5.5: users stay in control)."""
    state = user_state()
    groups = [
        ("Topics you follow", state.followed_pillars, "unfollow_topic", pillar_label, "Unfollow"),
        ("Sources you follow", state.followed_sources, "unfollow_source", str, "Unfollow"),
        ("Hidden topics", state.hidden_pillars, "unhide_topic", pillar_label, "Show again"),
    ]
    if not any(items for _, items, *_ in groups):
        return
    st.markdown("#### Follows and hidden topics")
    for title, items, action, label, button in groups:
        if not items:
            continue
        st.caption(title)
        for item in sorted(items):
            c1, c2 = st.columns([3, 1])
            c1.write(label(item))
            if c2.button(button, key=f"{action}-{item}"):
                act(action, value=item)


def page() -> None:
    profile = current_profile()
    email = profile.email if profile else st.session_state.get("pending_email")
    if email:
        preferences(email)
    else:
        sign_in()
