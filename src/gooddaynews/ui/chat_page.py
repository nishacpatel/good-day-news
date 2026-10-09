"""Conversational news (PRD sections 8.2, 19 and 20)."""

import itertools
from datetime import date, timedelta

import streamlit as st

from gooddaynews.rag.engine import Answer
from gooddaynews.rag.models import ChatSession, Filters
from gooddaynews.rag.prompts import verification_text
from gooddaynews.ui.common import chat_engine, current_profile, user_pillars

EXAMPLES = [
    "What good happened this week?",
    "Any conservation news from India?",
    "What progress has there been in science?",
    "Give me three encouraging environment stories.",
]
STORY_EXAMPLES = ["Explain this story in simple language.", "Why does this matter?", "How reliable is this?"]
GEOGRAPHY = {"Anywhere": [], "India": ["IN"], "Global / international": ["INT"]}


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


def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.chat = ChatSession()


def sidebar_filters(pillars: dict) -> Filters:
    with st.sidebar:
        st.header("Chat filters")
        labels = {p["label"]: key for key, p in pillars.items()}
        chosen = st.multiselect("Categories", list(labels), placeholder="All categories")
        where = st.selectbox("Geography", list(GEOGRAPHY))
        start = end = None
        if st.toggle("Limit to dates"):
            picked = st.date_input("Published between", (date.today() - timedelta(days=7), date.today()),
                                   max_value=date.today(), format="DD/MM/YYYY")
            if isinstance(picked, tuple) and len(picked) == 2:
                start, end = picked
        if st.button("Start a new conversation", use_container_width=True):
            reset_chat()
            st.session_state.pop("story_in_view", None)
            st.rerun()
    return Filters(pillars=[labels[c] for c in chosen], countries=GEOGRAPHY[where], start=start, end=end)


def page() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("chat", ChatSession())
    engine = chat_engine()
    filters = sidebar_filters(engine.pillars)
    in_view = st.session_state.get("story_in_view")

    st.markdown("## Ask about the news")
    st.caption("Answers come only from verified stories in this app, and every answer cites its sources.")
    if in_view:
        c1, c2 = st.columns([5, 1])
        c1.info(f"Asking about: **{in_view['headline']}**")
        if c2.button("Clear", help="Ask about all stories instead"):
            st.session_state.pop("story_in_view")
            st.rerun()

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
            options = STORY_EXAMPLES if in_view else EXAMPLES
            cols = st.columns(2)
            for i, example in enumerate(options):
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
                answer = engine.ask(prompt, st.session_state.chat, filters,
                                    story_id=in_view["id"] if in_view else None,
                                    user_topics=user_pillars(current_profile()))
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
