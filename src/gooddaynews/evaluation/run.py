"""Run the chat evaluation set (eval/questions.yaml).

    python -m gooddaynews.evaluation.run                    # all questions, new results file
    python -m gooddaynews.evaluation.run --resume FILE      # continue an interrupted run
    python -m gooddaynews.evaluation.run --only A1 N2       # just these questions
    python -m gooddaynews.evaluation.run --no-judge         # automatic checks only (fewer AI calls)

Each result is appended to eval/results/<run>.jsonl as soon as it is finished.
"""

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml

from gooddaynews.db import connect
from gooddaynews.evaluation.checks import check, passed
from gooddaynews.evaluation.judge import JUDGE_SYSTEM, Judgement, judge_prompt
from gooddaynews.llm import GeminiLLM, model_list
from gooddaynews.process.config import load_pillars
from gooddaynews.rag.engine import Answer, ChatEngine
from gooddaynews.rag.models import ChatSession
from gooddaynews.rag.prompts import story_block
from gooddaynews.settings import ROOT, get_settings

QUESTIONS = ROOT / "eval" / "questions.yaml"
RESULTS = ROOT / "eval" / "results"


def load_questions() -> tuple[date, list[dict]]:
    data = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    as_of = data["as_of"] if isinstance(data["as_of"], date) else date.fromisoformat(data["as_of"])
    return as_of, data["questions"]


def sources_text(answer: Answer) -> str:
    """Exactly the numbered sources the answer model saw, so [n] in the answer lines up."""
    return "\n\n".join(
        story_block(i, s, [p for p in answer.passages if p.story_id == s.id]) for i, s in enumerate(answer.stories, 1)
    )


def evaluate_one(engine: ChatEngine, llm: GeminiLLM, item: dict, as_of: date, judge: bool) -> dict:
    session = ChatSession()
    for earlier in item.get("before", []):
        engine.ask(earlier, session).complete()

    calls_before = llm.calls
    llm.last_answer_model = None
    started = time.monotonic()
    answer = engine.ask(item["question"], session, story_id=item.get("story_id")).complete()
    seconds = round(time.monotonic() - started, 1)
    answer_model = llm.last_answer_model

    cited = [{"n": c.number, "id": c.story.id, "headline": c.story.headline, "country": c.story.country,
              "date": c.story.published_at.date().isoformat() if c.story.published_at else None}
             for c in answer.citations]
    result = {
        "id": item["id"], "category": item["category"], "question": item["question"], "expect": item["expect"],
        "kind": answer.kind, "text": answer.text, "cited": cited, "error": answer.error,
        "retrieved": [s.id for s in answer.stories], "passages": len(answer.passages), "seconds": seconds,
        "intent": answer.plan.intent if answer.plan else None,
    }
    context = sources_text(answer)
    result["checks"] = check(item, result, context, as_of)

    result["answer_model"], result["judge_model"], result["judge"] = answer_model, None, None
    if judge and answer.kind == "answer":
        # Never let a model grade its own answer.
        judges = [m for m in model_list(get_settings().judge_model) if m != answer_model and m not in llm.exhausted]
        try:
            if not judges:
                raise RuntimeError("no judge model available that differs from the answer model")
            used_before = dict(llm.used)
            j = llm.generate_json(judge_prompt(item["question"], context, answer.text, item.get("premise")),
                                  Judgement, system=JUDGE_SYSTEM, models=",".join(judges))
            result["judge"] = j.model_dump()
            result["judge_model"] = next((m for m in llm.used if llm.used[m] > used_before.get(m, 0)), None)
        except Exception as exc:
            result["judge"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    result["sources"] = context  # kept so the answer can be re-graded or checked by hand later
    result["llm_calls"] = llm.calls - calls_before
    result["passed"] = passed(result["checks"]) and (
        result["judge"] is None or "error" in result["judge"]
        or (result["judge"]["accuracy"] != "unsupported" and result["judge"]["premise"] != "accepted"))
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resume", type=Path, help="results file to continue")
    p.add_argument("--only", nargs="+", help="question ids to run")
    p.add_argument("--no-judge", action="store_true")
    args = p.parse_args(argv)

    as_of, questions = load_questions()
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = args.resume or RESULTS / f"run-{datetime.now():%Y%m%d-%H%M}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(line)["id"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}

    llm = GeminiLLM()
    engine = ChatEngine(llm, connect, load_pillars(), today=lambda: as_of)
    print(f"Evaluating {len(questions) - len(done & {q['id'] for q in questions})} question(s) as of {as_of} -> {out}")
    for item in questions:
        if item["id"] in done:
            continue
        try:
            r = evaluate_one(engine, llm, item, as_of, judge=not args.no_judge)
        except Exception as exc:  # e.g. every model out of quota: stop, keep what we have, resume later
            print(f"  {item['id']}: stopped ({type(exc).__name__}: {str(exc)[:150]}). Resume with --resume {out}")
            return 1
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        judge = r["judge"]["accuracy"] if r["judge"] and "accuracy" in r["judge"] else "-"
        print(f"  {r['id']:<3} {'PASS' if r['passed'] else 'FAIL'}  {r['kind']:<12} judge={judge:<17} "
              f"cited={[c['id'] for c in r['cited']]} {r['seconds']}s  "
              f"[answer: {r['answer_model'] or '-'}, judge: {r['judge_model'] or '-'}]")
    print(f"Done. Models used: {llm.used}. Build the report with: python -m gooddaynews.evaluation.report {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
