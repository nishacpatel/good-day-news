"""Story detail page (PRD section 23). Reached by link: /story?id=42, so stories can be shared."""

import streamlit as st

from gooddaynews import feedback
from gooddaynews.explore import story_detail
from gooddaynews.ui import nav
from gooddaynews.ui.common import current_profile, db, pillar_label, place_text, verification_short
from gooddaynews.ui.components import story_actions


def page() -> None:
    try:
        story_id = int(st.query_params.get("id", ""))
    except ValueError:
        st.info("Choose a story from Today's Briefing or Explore.")
        nav.link("explore", "Go to Explore", "🧭")
        return
    with db() as conn:
        detail = story_detail(conn, story_id)
        profile = current_profile()
        if detail and profile and st.session_state.get("last_read") != story_id:
            feedback.record(conn, profile.id, "read", story_id)  # engagement metric (PRD 31)
            st.session_state.last_read = story_id
    if detail is None:
        st.warning("This story isn't available. It may have been removed.")
        nav.link("explore", "Go to Explore", "🧭")
        return

    s = detail.story
    st.caption(pillar_label(s.pillar).upper() + (f" · {s.subcategory}" if s.subcategory else ""))
    st.markdown(f"## {s.headline}")
    when = s.published_at.strftime("%d %B %Y") if s.published_at else "Date unknown"
    likes = f" · {detail.likes} like{'s' if detail.likes != 1 else ''}" if detail.likes else ""
    st.caption(f"{place_text(s.place, s.country)} · {when} · {verification_short(s.verification_level, s.source_count)}"
               f"{likes}")
    st.write(s.summary)
    if s.why_it_matters:
        st.markdown(f"**Why it matters:** {s.why_it_matters}")
    if detail.key_facts:
        st.markdown("**Key facts**")
        st.markdown("\n".join(f"- {f}" for f in detail.key_facts))

    st.markdown(f"**Sources** ({len(s.sources)})")
    st.markdown("\n".join(f"- [{name}]({url})" for name, url, _ in s.sources))
    story_actions(s, key=f"d{s.id}", show_details=False)

    with st.expander("Why this story was included"):
        st.write(detail.why_included or "No record.")
        st.caption("Stories are scored for constructive impact, significance, source credibility, human impact, "
                   "novelty, evidence and emotional value. Only stories above the threshold are published.")

    if detail.related:
        st.markdown("#### Related stories")
        for r in detail.related:
            nav.link("story", r.headline, "📰", id=r.id)
    st.caption(f"Related topic: {pillar_label(s.pillar)}")
