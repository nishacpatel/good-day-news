"""RAG chat engine.

    1 interpret   one cheap LLM call: standalone question, intent, keywords, dates, filters
    2 stories     semantic + keyword search over stories, within filters
    3 passages    semantic search over chunks of the chosen stories only
    4 rerank      relevance + recency + constructive score + user preference
    5 generate    streamed answer from the numbered sources only
    6 cite        keep valid [n] citations, map them to stories, or refuse
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta

from gooddaynews.llm import LLM
from gooddaynews.rag import retrieve
from gooddaynews.rag.config import RagConfig, load_rag
from gooddaynews.rag.models import ChatSession, Citation, Filters, Passage, QueryPlan, StoryHit
from gooddaynews.rag.prompts import ANSWER_SYSTEM, INTERPRET_SYSTEM, answer_prompt, interpret_prompt
from gooddaynews.rag.rank import pick_passages, reciprocal_rank_fusion, rerank

OUT_OF_SCOPE_MESSAGE = (
    "I can only help with questions about the news in my collection, such as progress in science, the "
    "environment, health or your community. Try asking “What good happened in India this week?”"
)
# Relevance added to stories cited in the previous answer when the user asks a follow-up.
RECENT_STORY_BOOST = 0.5
UNAVAILABLE_MESSAGE = "The assistant is unavailable right now (the AI service did not respond). Please try again later."
# Keyword matches still need to be somewhat related in meaning, so a shared word alone is not enough.
KEYWORD_SIMILARITY_MARGIN = 0.05
_CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass
class Answer:
    question: str
    plan: QueryPlan | None
    stories: list[StoryHit] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    kind: str = "answer"  # answer | refused | out_of_scope | error
    text: str = ""
    citations: list[Citation] = field(default_factory=list)
    error: str | None = None
    _pieces: Iterator[str] | None = None
    _on_done: Callable[["Answer"], None] | None = None

    @property
    def refused(self) -> bool:
        return self.kind == "refused"

    def stream(self) -> Iterator[str]:
        """Yield the answer as it is written. Afterwards `text` and `citations` are final."""
        if self._pieces is None:
            yield self.text
        else:
            parts = []
            try:
                for piece in self._pieces:
                    parts.append(piece)
                    yield piece
                self.text = "".join(parts).strip()
                if not self.text:
                    raise RuntimeError("empty answer")
            except Exception as exc:
                self.kind = "error"
                self.text = UNAVAILABLE_MESSAGE
                self.error = f"{type(exc).__name__}: {exc}"[:300]
                yield ("\n\n" if parts else "") + UNAVAILABLE_MESSAGE
            self._pieces = None
        if self._on_done:
            self._on_done(self)
            self._on_done = None

    def complete(self) -> "Answer":
        """Consume the stream without displaying it (CLI, tests, evaluation)."""
        for _ in self.stream():
            pass
        return self


def finalize_citations(answer: Answer, refusal_message: str) -> None:
    """Keep only citations that point at a provided story; detect refusals."""
    if answer.kind != "answer":
        return
    if refusal_message.rstrip(".").lower() in answer.text.lower() and len(answer.text) < len(refusal_message) + 40:
        answer.kind, answer.text, answer.citations = "refused", refusal_message, []
        return
    valid = {i: s for i, s in enumerate(answer.stories, 1)}
    answer.text = _CITATION_RE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", answer.text)
    used = sorted({int(n) for n in _CITATION_RE.findall(answer.text)})
    answer.citations = [Citation(n, valid[n]) for n in used]


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def merge_filters(ui: Filters | None, plan: QueryPlan, pillars: dict, cfg: RagConfig, today: date) -> Filters:
    """Filters chosen in the app win; otherwise use what the question implies."""
    ui = ui or Filters()
    f = Filters(
        pillars=ui.pillars or [p for p in plan.pillars if p in pillars],
        countries=ui.countries or [c.upper() for c in plan.countries if len(c) in (2, 3)],
        start=ui.start or parse_date(plan.start_date),
        end=ui.end or parse_date(plan.end_date),
    )
    if plan.broad and not f.start:
        f.start = today - timedelta(days=cfg.default_days_back)
    return f


def fallback_plan(question: str) -> QueryPlan:
    return QueryPlan(standalone_question=question, intent="news_search", broad=False, keywords=[],
                     start_date="", end_date="", pillars=[], countries=[])


class ChatEngine:
    def __init__(self, llm: LLM, connect: Callable, pillars: dict, cfg: RagConfig | None = None,
                 today: Callable[[], date] = date.today):
        self.llm, self.connect, self.pillars = llm, connect, pillars
        self.cfg = cfg or load_rag()
        self.today = today

    def interpret(self, question: str, session: ChatSession, story_in_view: str | None) -> QueryPlan:
        try:
            return self.llm.generate_json(
                interpret_prompt(question, self.today(), session.turns, self.pillars, story_in_view),
                QueryPlan, system=INTERPRET_SYSTEM, fast=True,
            )
        except Exception:
            return fallback_plan(question)  # searching with the raw question is better than failing

    def _refuse(self, question: str, plan: QueryPlan, session: ChatSession) -> Answer:
        answer = Answer(question, plan, kind="refused", text=self.cfg.refusal_message)
        answer._on_done = lambda a: self._remember(session, a)
        return answer

    def _remember(self, session: ChatSession, answer: Answer) -> None:
        finalize_citations(answer, self.cfg.refusal_message)
        if answer.kind == "error":
            return  # do not add a failed turn to the conversation
        session.add("user", answer.question, self.cfg.history_turns)
        session.add("assistant", answer.text, self.cfg.history_turns)
        if answer.citations:
            session.last_story_ids = [c.story.id for c in answer.citations]

    def ask(self, question: str, session: ChatSession, filters: Filters | None = None,
            story_id: int | None = None, user_topics: list[str] | None = None) -> Answer:
        cfg, today = self.cfg, self.today()
        conn = self.connect()
        try:
            in_view = retrieve.load_stories(conn, [story_id]).get(story_id) if story_id else None
            plan = self.interpret(question, session, in_view.headline if in_view else None)
            if plan.intent == "out_of_scope":
                answer = Answer(question, plan, kind="out_of_scope", text=OUT_OF_SCOPE_MESSAGE)
                answer._on_done = lambda a: self._remember(session, a)
                return answer
            if plan.intent == "personal" and not session.last_story_ids:
                plan.broad = True
            f = merge_filters(filters, plan, self.pillars, cfg, today)

            # The story open on screen always stays in. Stories from the previous answer get a boost,
            # but must still compete, because a follow-up can be about a different story.
            pinned = [story_id] if story_id else []
            recent = [i for i in session.last_story_ids if i not in pinned] if plan.intent in (
                "story_followup", "verification", "personal") else []

            qvec = self.llm.embed([plan.standalone_question], task="RETRIEVAL_QUERY")[0]
            vec_hits = retrieve.story_vector_search(conn, qvec, f, cfg.story_candidates)
            sims = dict(vec_hits)
            semantic = [i for i, s in vec_hits if s >= cfg.min_story_similarity]
            keyword = [i for i, _ in retrieve.story_keyword_search(conn, plan.keywords, f, cfg.story_candidates)
                       if sims.get(i, 0.0) >= cfg.min_story_similarity - KEYWORD_SIMILARITY_MARGIN]
            broad = retrieve.recent_story_ids(conn, f, cfg.story_candidates) if plan.broad else []
            fused = reciprocal_rank_fusion(semantic, keyword, broad)

            ids = list(dict.fromkeys(pinned + list(fused) + recent))
            if not ids:
                return self._refuse(question, plan, session)
            loaded = retrieve.load_stories(conn, ids)
            for sid, s in loaded.items():
                s.similarity = sims.get(sid, 0.0)
                if sid in pinned:
                    s.relevance = 1.0
                else:
                    s.relevance = min(1.0, fused.get(sid, 0.0) + (RECENT_STORY_BOOST if sid in recent else 0.0))
            ranked = rerank(list(loaded.values()), cfg, user_topics)
            chosen = [s for s in ranked if s.id in pinned]
            chosen += [s for s in ranked if s.id not in pinned][: max(0, cfg.max_stories - len(chosen))]

            passages = pick_passages(
                retrieve.passage_search(conn, qvec, [s.id for s in chosen], cfg.max_passages * 3), cfg
            )
        finally:
            conn.close()

        answer = Answer(question, plan, stories=chosen, passages=passages)
        answer._pieces = self.llm.stream_text(
            answer_prompt(plan.standalone_question, today, chosen, passages, session.turns, user_topics),
            system=ANSWER_SYSTEM.format(refusal=cfg.refusal_message),
        )
        answer._on_done = lambda a: self._remember(session, a)
        return answer
