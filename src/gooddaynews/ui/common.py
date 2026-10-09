"""Shared Streamlit helpers: cached services, the signed-in profile, display formatting."""

from contextlib import contextmanager

import streamlit as st

from gooddaynews.briefing.models import Profile, load_briefing_config
from gooddaynews.db import connect
from gooddaynews.llm import GeminiLLM
from gooddaynews.process.config import load_pillars, load_scoring
from gooddaynews.rag.engine import ChatEngine

COUNTRY_NAMES = {"IN": "India", "INT": "Global", "US": "United States", "GB": "United Kingdom", "AU": "Australia",
                 "CN": "China", "JP": "Japan", "KE": "Kenya", "BR": "Brazil", "EG": "Egypt", "KR": "South Korea",
                 "CA": "Canada", "DE": "Germany", "FR": "France", "ZA": "South Africa", "NG": "Nigeria"}
VERIFICATION_SHORT = {
    "multiple_sources": "Reported by {n} sources",
    "primary_source": "Primary source",
    "research": "Based on research",
    "official_data": "Based on official data",
    "single_source": "Single source",
    "opinion": "Opinion",
}


@st.cache_resource
def llm() -> GeminiLLM:
    return GeminiLLM()


@st.cache_resource
def chat_engine() -> ChatEngine:
    return ChatEngine(llm(), connect, load_pillars())


@st.cache_resource
def configs():
    return load_pillars(), load_briefing_config(), load_scoring()


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def current_profile() -> Profile | None:
    return st.session_state.get("profile")


def pillar_label(key: str) -> str:
    return configs()[0].get(key, {}).get("label", key.title())


def place_text(place: str | None, country: str | None) -> str:
    country_name = COUNTRY_NAMES.get(country or "", country or "")
    return ", ".join(x for x in (place, country_name) if x) or "Location not stated"


def verification_short(level: str, source_count: int) -> str:
    return VERIFICATION_SHORT.get(level, "Single source").format(n=source_count)


def user_pillars(profile: Profile | None) -> list[str]:
    if not profile:
        return []
    topics = configs()[1].topics
    return sorted({p for t in profile.topics for p in topics.get(t, [])})
