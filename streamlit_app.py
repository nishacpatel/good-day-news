"""Constructive News AI: web app.

    .venv\\Scripts\\python -m streamlit run streamlit_app.py
"""

import streamlit as st

from gooddaynews.ui import briefing_page, chat_page, explore_page, nav, profile_page, story_page

st.set_page_config(page_title="Constructive News AI", page_icon="☀️", layout="centered")

nav.PAGES.update(
    briefing=st.Page(briefing_page.page, title="Today's Briefing", icon="☀️", url_path="briefing", default=True),
    explore=st.Page(explore_page.page, title="Explore", icon="🧭", url_path="explore"),
    chat=st.Page(chat_page.page, title="Ask AI", icon="💬", url_path="chat"),
    profile=st.Page(profile_page.page, title="My preferences", icon="⚙️", url_path="preferences"),
    story=st.Page(story_page.page, title="Story", icon="📰", url_path="story", visibility="hidden"),
)

try:
    st.navigation(list(nav.PAGES.values())).run()
except RuntimeError as exc:  # missing API key or database settings
    st.error(f"The app is not configured: {exc}")
