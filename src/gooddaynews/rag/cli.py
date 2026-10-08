"""Chat with the news from the terminal.

    python -m gooddaynews.rag.cli "What conservation news is there from India?"
    python -m gooddaynews.rag.cli            # interactive; empty line to quit
"""

import sys

from gooddaynews.db import connect
from gooddaynews.llm import GeminiLLM
from gooddaynews.process.config import load_pillars
from gooddaynews.rag.engine import Answer, ChatEngine
from gooddaynews.rag.models import ChatSession


def print_answer(answer: Answer) -> None:
    for piece in answer.stream():
        print(piece, end="", flush=True)
    print()
    for c in answer.citations:
        s = c.story
        when = s.published_at.strftime("%d %b %Y") if s.published_at else "date unknown"
        links = ", ".join(f"{src.name} <{src.url}>" for src in s.sources[:3])
        print(f"  [{c.number}] {s.headline} ({when}) {links}")
    plan = answer.plan
    if plan:
        print(f"  ({answer.kind}; intent={plan.intent}, broad={plan.broad}, keywords={plan.keywords}, "
              f"dates={plan.start_date or '-'}..{plan.end_date or '-'}, stories={len(answer.stories)}, "
              f"passages={len(answer.passages)})")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    engine = ChatEngine(GeminiLLM(), connect, load_pillars())
    session = ChatSession()
    if argv:
        print_answer(engine.ask(" ".join(argv), session))
        return 0
    while (question := input("\nYou: ").strip()):
        print_answer(engine.ask(question, session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
