"""Constructive News AI: chat interface.

    .venv\\Scripts\\streamlit run streamlit_app.py
"""

import itertools
from datetime import date, timedelta

import streamlit as st

from gooddaynews.db import connect
from gooddaynews.llm import GeminiLLM
from gooddaynews.process.config import load_pillars
from gooddaynews.rag.engine import Answer, ChatEngine
from gooddaynews.rag.models import ChatSession, Filters
from gooddaynews.rag.prompts import verification_text

st.set_page_config(page_title="Constructive News AI", page_icon="☀️", layout="centered")

EXAMPLES = [
    "What good happened this week?",
    "Any conservation news from India?",
    "What progress has there been in science?",
    "Give me three encouraging environment stories.",
]
GEOGRAPHY = {"Anywhere": [], "India": ["IN"], "Global / international": ["INT"]}


@st.cache_resource
def get_engine() -> ChatEngine:
    return ChatEngine(GeminiLLM(), connect, load_pillars())


def sources_markdown(citations: list[dict]) -> str:
    lines = []
    for c in citations:
        links = " · ".join(f"[{s['name']}]({s['url']})" for s in c["sources"][:3])
        lines.append(f"**[{c['number']}]** {c['headline']}  \n{c['date']} · {c['verification']} · {links}")
    return "\n\n".join(lines)


def citation_records(answer: Answer) -> list[dict]:
    return [
        {
            "number": c.number,
            "headline": c.story.headline,
            "date": c.story.published_at.strftime("%d %b %Y") if c.story.published_at else "date unknown",
            "verification": verification_text(c.story).capitalize(),
            "sources": [{"name": s.name, "url": s.url} for s in c.story.sources],
        }
        for c in answer.citations
    ]


def sidebar_filters(pillars: dict) -> Filters:
    with st.sidebar:
        st.header("Filters")
        labels = {p["label"]: key for key, p in pillars.items()}
        chosen = st.multiselect("Categories", list(labels), placeholder="All categories")
        where = st.selectbox("Geography", list(GEOGRAPHY))
        limit_dates = st.toggle("Limit to dates")
        start = end = None
        if limit_dates:
            picked = st.date_input("Published between", (date.today() - timedelta(days=7), date.today()),
                                   max_value=date.today(), format="DD/MM/YYYY")
            if isinstance(picked, tuple) and len(picked) == 2:
                start, end = picked
        st.divider()
        if st.button("Start a new conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.chat = ChatSession()
            st.rerun()
        st.caption("Answers come only from verified news stories in this app, with sources. "
                   "This app complements, not replaces, regular news.")
    return Filters(pillars=[labels[c] for c in chosen], countries=GEOGRAPHY[where], start=start, end=end)


def main() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("chat", ChatSession())

    try:
        engine = get_engine()
    except RuntimeError as exc:
        st.error(f"The app is not configured: {exc}")
        st.stop()

    filters = sidebar_filters(engine.pillars)

    st.title("☀️ Constructive News AI")
    st.caption("Ask about what went right in the world. Every answer cites its sources.")

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["text"])
            if m.get("citations"):
                with st.expander(f"Sources ({len(m['citations'])})"):
                    st.markdown(sources_markdown(m["citations"]))

    prompt = st.chat_input("Ask about the news, e.g. “What good happened in India this week?”")
    if not st.session_state.messages and not prompt:
        examples = st.empty()
        with examples.container():
            st.write("Try one of these:")
            cols = st.columns(2)
            for i, example in enumerate(EXAMPLES):
                if cols[i % 2].button(example, use_container_width=True):
                    prompt = example
        if prompt:
            examples.empty()
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching the news…"):
                answer = engine.ask(prompt, st.session_state.chat, filters)
            pieces = answer.stream()
            with st.spinner("Writing the answer…"):
                first = next(pieces, "")  # the model thinks before its first words arrive
            st.write_stream(itertools.chain([first], pieces))
        except Exception as exc:
            st.error("Something went wrong while answering. Please try again.")
            st.caption(f"{type(exc).__name__}: {str(exc)[:200]}")
            return
        citations = citation_records(answer)
        if citations:
            with st.expander(f"Sources ({len(citations)})", expanded=True):
                st.markdown(sources_markdown(citations))
    st.session_state.messages.append({"role": "assistant", "text": answer.text, "citations": citations})


main()
