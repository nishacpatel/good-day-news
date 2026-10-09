"""Page registry, so pages can link to each other. Filled in by streamlit_app.py on every run."""

import streamlit as st

PAGES: dict[str, "st.Page"] = {}


def go(name: str) -> None:
    st.switch_page(PAGES[name])


def link(name: str, label: str, icon: str | None = None) -> None:
    st.page_link(PAGES[name], label=label, icon=icon)
