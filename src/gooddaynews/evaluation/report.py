"""Build the evaluation report (docs/evaluation_report.md) from a results file and the labelled sets.

    python -m gooddaynews.evaluation.report eval/results/run-YYYYMMDD-HHMM.jsonl [eval/results/baseline-....jsonl]
"""

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from gooddaynews.evaluation.judge import ACCURACY_POINTS, CITATION_POINTS
from gooddaynews.settings import ROOT

REPORT = ROOT / "docs" / "evaluation_report.md"
CATEGORY_NAMES = {"factual": "Answerable facts", "filtered": "Filtered / multi-story", "recency": "Time-based",
                  "follow_up": "Follow-ups and story in view", "verification": "Reliability questions",
                  "unanswerable": "Not in the collection", "out_of_scope": "Off-topic", "trap": "False premises"}


def pct(n: int | float, d: int) -> str:
    return f"{n / d:.0%}" if d else "n/a"


def rate(items: list[dict], key: str) -> tuple[int, int]:
    vals = [r["checks"][key] for r in items if r["checks"].get(key) is not None]
    return sum(1 for v in vals if v), len(vals)


def chat_metrics(results: list[dict]) -> dict:
    answerable = [r for r in results if r["expect"] == "answer"]
    answered = [r for r in answerable if r["kind"] == "answer"]
    judged = [r for r in answered if r.get("judge") and "accuracy" in r["judge"]]
    m = {
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "accuracy_judge": statistics.mean(ACCURACY_POINTS[r["judge"]["accuracy"]] for r in judged) if judged else None,
        "judged": len(judged),
        "facts": rate(answered, "mentions"),
        "cites_expected": rate(answered, "cites_expected"),
        "has_citations": rate(answered, "has_citations"),
        "citation_judge": statistics.mean(CITATION_POINTS[r["judge"]["citations"]] for r in judged) if judged else None,
        "recency": rate(results, "recency"),
        "country": rate(results, "country"),
        "false_refusals": sum(1 for r in answerable if r["kind"] != "answer"),
        "answerable": len(answerable),
    }
    unans = [r for r in results if r["category"] == "unanswerable"]
    off = [r for r in results if r["category"] == "out_of_scope"]
    traps = [r for r in results if r["category"] == "trap"]
    trap_ok = [r for r in traps if r["kind"] == "refused"
               or (r["kind"] == "answer" and r.get("judge") and r["judge"].get("premise") != "accepted")]
    m["refused_unanswerable"] = (sum(r["kind"] == "refused" for r in unans), len(unans))
    m["out_of_scope_ok"] = (sum(r["kind"] == "out_of_scope" for r in off), len(off))
    m["traps_ok"] = (len(trap_ok), len(traps))
    m["unanswerable_handling"] = (m["refused_unanswerable"][0] + m["out_of_scope_ok"][0] + len(trap_ok),
                                  len(unans) + len(off) + len(traps))
    secs = [r["seconds"] for r in results]
    m["median_seconds"] = statistics.median(secs)
    m["p90_seconds"] = sorted(secs)[int(0.9 * (len(secs) - 1))]
    return m


def failure_reason(r: dict) -> str:
    c, reasons = r["checks"], []
    if not c["outcome"]:
        reasons.append(f"expected {r['expect']}, got {r['kind']}")
    for key, text in (("cites_expected", "did not cite the expected story"), ("has_citations", "no citations"),
                      ("country", "cited a story from another country"), ("recency", "cited a story outside the dates"),
                      ("avoids_forbidden", "used a forbidden phrase")):
        if c.get(key) is False:
            reasons.append(text)
    if c.get("mentions") is False:
        reasons.append(f"missing: {', '.join(c['missing_mentions'])}")
    j = r.get("judge") or {}
    if j.get("accuracy") == "unsupported":
        reasons.append("judge: unsupported claims")
    if j.get("premise") == "accepted":
        reasons.append("judge: accepted the false premise")
    return "; ".join(reasons) or "-"


def classification_metrics(conn) -> dict | None:
    path = ROOT / "eval" / "classification_labels.yaml"
    if not path.exists():
        return None
    labels = yaml.safe_load(path.read_text(encoding="utf-8"))["labels"]
    status = dict(conn.run("select id, status from stories where id = any(cast(:ids as bigint[]))",
                           ids=[x["id"] for x in labels]))
    rows = []
    for x in labels:
        predicted = "keep" if status.get(x["id"]) == "published" else "reject"
        rows.append({**x, "predicted": predicted})
    headlines = dict(conn.run("select id, headline from stories where id = any(cast(:ids as bigint[]))",
                              ids=[x["id"] for x in labels]))
    tp = sum(r["label"] == "keep" and r["predicted"] == "keep" for r in rows)
    fp = sum(r["label"] == "reject" and r["predicted"] == "keep" for r in rows)
    fn = sum(r["label"] == "keep" and r["predicted"] == "reject" for r in rows)
    agree = sum(r["label"] == r["predicted"] for r in rows)
    return {"n": len(rows), "agree": agree, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn,
            "disagreements": [{**r, "headline": headlines.get(r["id"], "")} for r in rows if r["label"] != r["predicted"]]}


def dedupe_metrics() -> dict | None:
    path = ROOT / "eval" / "dedupe_labels.yaml"
    if not path.exists():
        return None
    pairs = yaml.safe_load(path.read_text(encoding="utf-8"))["pairs"]
    out = {"n": len(pairs), "same": sum(p["same"] for p in pairs), "thresholds": []}
    for t in (0.85, 0.86, 0.875, 0.90):
        tp = sum(p["same"] and p["similarity"] >= t for p in pairs)
        fp = sum(not p["same"] and p["similarity"] >= t for p in pairs)
        fn = sum(p["same"] and p["similarity"] < t for p in pairs)
        out["thresholds"].append({"t": t, "tp": tp, "fp": fp, "fn": fn,
                                  "precision": tp / (tp + fp) if tp + fp else None,
                                  "recall": tp / (tp + fn) if tp + fn else None})
    return out


def fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def load_results(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def comparison(baseline: list[dict], final: list[dict]) -> list[str]:
    b, f = chat_metrics(baseline), chat_metrics(final)
    rows = [
        ("Questions passed", f"{b['passed']}/{b['total']}", f"{f['passed']}/{f['total']}"),
        ("Accuracy (judge)", fmt(b["accuracy_judge"]), fmt(f["accuracy_judge"])),
        ("Cited the expected story", pct(*b["cites_expected"]), pct(*f["cites_expected"])),
        ("Recency", pct(*b["recency"]), pct(*f["recency"])),
        ("Unanswerable handling", pct(*b["unanswerable_handling"]), pct(*f["unanswerable_handling"])),
        ("Wrong refusals", f"{b['false_refusals']}/{b['answerable']}", f"{f['false_refusals']}/{f['answerable']}"),
    ]
    lines = ["## First run compared with the run after fixes", "", "| Measure | First run | After fixes |",
             "|---|---|---|"]
    lines += [f"| {name} | {x} | {y} |" for name, x, y in rows]
    failed = [r for r in baseline if not r["passed"]]
    if failed:
        lines += ["", "First-run failures:", ""]
        lines += [f"- **{r['id']}** ({r['question']}): {failure_reason(r)}" for r in failed]
    return lines + [""]


def build(results_path: Path, baseline_path: Path | None = None) -> str:
    from gooddaynews.db import connect

    results = load_results(results_path)
    m = chat_metrics(results)
    conn = connect()
    try:
        cls = classification_metrics(conn)
    finally:
        conn.close()
    dd = dedupe_metrics()
    q = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text(encoding="utf-8"))

    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    unh = m["unanswerable_handling"]
    L = []
    L += [
        "# Evaluation report: Constructive News AI",
        "",
        f"Run `{results_path.name}` · data as of {q['as_of']} · {m['total']} questions · "
        f"{len({s for r in results for s in r['retrieved']})} distinct stories retrieved",
        "",
        "## Summary",
        "",
        "| Criterion (from the capstone brief) | Score | How it is measured |",
        "|---|---|---|",
        f"| **Accuracy** | **{fmt(m['accuracy_judge'])}** | Judge model grades each answer against the exact sources it "
        f"was given (supported 1, partly 0.5, unsupported 0); {m['judged']} answers. Required facts present: "
        f"{m['facts'][0]}/{m['facts'][1]}. |",
        f"| **Citation correctness** | **{pct(*m['cites_expected'])}** | Answer cited the story that contains the answer: "
        f"{m['cites_expected'][0]}/{m['cites_expected'][1]}. Judge: citations support their sentences {fmt(m['citation_judge'])}. "
        f"Answers with at least one citation: {m['has_citations'][0]}/{m['has_citations'][1]}. |",
        f"| **Recency** | **{pct(*m['recency'])}** | Every cited story falls inside the asked-for dates "
        f"(\"today\", \"yesterday\", \"this week\"): {m['recency'][0]}/{m['recency'][1]}. |",
        f"| **Unanswerable handling** | **{pct(*unh)}** | Refused questions not in the collection "
        f"{m['refused_unanswerable'][0]}/{m['refused_unanswerable'][1]}, declined off-topic requests "
        f"{m['out_of_scope_ok'][0]}/{m['out_of_scope_ok'][1]}, did not accept false premises "
        f"{m['traps_ok'][0]}/{m['traps_ok'][1]}. Wrong refusals of answerable questions: "
        f"{m['false_refusals']}/{m['answerable']}. |",
        "",
        f"**Overall: {m['passed']}/{m['total']} questions passed every check.** "
        f"Median answer time {m['median_seconds']:.0f} s (90th percentile {m['p90_seconds']:.0f} s) on the Gemini free tier.",
        "",
    ]
    findings = ROOT / "eval" / "findings.md"  # written by hand after reading the results
    if findings.exists():
        L += [findings.read_text(encoding="utf-8").strip(), ""]
    if baseline_path:
        L += comparison(load_results(baseline_path), results)
    judges = {r.get("judge_model") for r in results if r.get("judge_model")}
    answerers = {r.get("answer_model") for r in results if r.get("answer_model")}
    if judges or answerers:
        same = sum(1 for r in results if r.get("judge_model") and r.get("judge_model") == r.get("answer_model"))
        L += [f"Answers written by: {', '.join(sorted(answerers))}. Graded by: {', '.join(sorted(judges))}. "
              f"Answers graded by the model that wrote them: {same}.", ""]
    L += [
        "## Results by question type",
        "",
        "| Type | Passed |",
        "|---|---|",
    ]
    for cat, name in CATEGORY_NAMES.items():
        if by_cat[cat]:
            L.append(f"| {name} | {sum(r['passed'] for r in by_cat[cat])}/{len(by_cat[cat])} |")

    L += ["", "## Every question", "", "| Id | Question | Expected | Got | Judge | Pass | Problem |", "|---|---|---|---|---|---|---|"]
    for r in results:
        j = r.get("judge") or {}
        judge = j.get("accuracy", "-") if "accuracy" in j else ("error" if j else "-")
        L.append(f"| {r['id']} | {r['question']} | {r['expect']} | {r['kind']} | {judge} | "
                 f"{'✅' if r['passed'] else '❌'} | {failure_reason(r) if not r['passed'] else ''} |")

    flagged = [r for r in results if r["checks"].get("unsupported_numbers")]
    L += ["", "## Numbers to review", "",
          "Numbers in an answer that don't appear in its sources. Usually rounding (\"over 1,200\" for 1,203) or "
          "dates written differently; anything else would be an invented figure.", ""]
    if flagged:
        for r in flagged:
            L.append(f"- **{r['id']}**: {', '.join(r['checks']['unsupported_numbers'])}")
    else:
        L.append("- None. Every number in every answer appears in its sources.")
    claims = [(r["id"], c) for r in results for c in (r.get("judge") or {}).get("unsupported_claims", []) or []]
    L += ["", "Claims the judge marked as not supported by the sources:", ""]
    L += [f"- **{i}**: {c}" for i, c in claims] or ["- None."]

    good = next((r for r in results if r["passed"] and r["category"] == "factual"), None)
    refusal = next((r for r in results if r["category"] == "unanswerable" and r["kind"] == "refused"), None)
    trap = next((r for r in results if r["category"] == "trap" and r["kind"] == "answer"), None)
    L += ["", "## Example answers", ""]
    for title, r in (("A grounded answer", good), ("A refusal", refusal), ("A false premise", trap)):
        if r:
            cites = "; ".join(f"[{c['n']}] {c['headline']}" for c in r["cited"])
            L += [f"**{title}** ({r['id']}): *{r['question']}*", "", "> " + r["text"].replace("\n", "\n> "), ""]
            if cites:
                L += [f"Cited: {cites}", ""]

    if cls:
        L += ["## Story scoring (keep or reject)", "",
              f"{cls['n']} stored stories were labelled by hand and compared with the pipeline's decisions.", "",
              f"- Agreement: **{cls['agree']}/{cls['n']} ({pct(cls['agree'], cls['n'])})**",
              f"- Precision for \"keep\" (kept stories that should be kept): {fmt(cls['precision'])}",
              f"- Recall for \"keep\" (stories that should be kept and were): {fmt(cls['recall'])}", "",
              "| Story | Label | Pipeline | Reason for label |", "|---|---|---|---|"]
        for d in cls["disagreements"]:
            L.append(f"| {d['headline'][:70]} | {d['label']} | {d['predicted']} | {d['reason']} |")
        L.append("")

    if dd:
        L += ["## Duplicate detection", "",
              f"{dd['n']} pairs measured on live data, labelled \"same event\" ({dd['same']}) or different "
              f"({dd['n'] - dd['same']}). The threshold in use was chosen after seeing these pairs, so its score here "
              "shows it separates the cases seen so far, not how it will do on new ones.", "",
              "| Threshold | Correct merges | Wrong merges | Missed duplicates | Precision | Recall |",
              "|---|---|---|---|---|---|"]
        for t in dd["thresholds"]:
            mark = " (in use)" if t["t"] == 0.875 else ""
            L.append(f"| {t['t']}{mark} | {t['tp']} | {t['fp']} | {t['fn']} | {fmt(t['precision'])} | {fmt(t['recall'])} |")
        L.append("")

    n_cls = cls["n"] if cls else 0
    n_dd = dd["n"] if dd else 0
    L += ["## Limitations", "",
          f"- **Small sample.** {m['total']} questions, {n_cls} labelled stories and {n_dd} duplicate pairs from about "
          f"two days of news. Each question moves a chat score by about {100 / m['total']:.0f} percentage points.",
          "- **Labels are the developer's.** The keep/reject and duplicate labels apply the PRD's principles but were "
          "not checked by an independent panel.",
          "- **Same model family, lenient judge.** The judge never grades its own answer, but it is a lighter Gemini "
          "model from the same family and may share blind spots. Check a sample by hand (see Findings).",
          "- **Answers vary.** The same question can get a slightly different answer each time; borderline items "
          "can flip between runs.",
          "- **Free-tier limits.** Daily and per-minute quotas shaped the design (model fallbacks, pacing) and make "
          "answers slow (median above). Embeddings are capped at 1,000 texts a day, which limits how much news can "
          "be processed daily and stopped the duplicate-pair measurement on the evaluation day. A paid tier would "
          "mainly change speed and volume, not the approach.",
          "", "## How to reproduce", "",
          "```", "python -m gooddaynews.evaluation.run", "python -m gooddaynews.evaluation.report eval/results/<run>.jsonl", "```",
          "", "Questions: `eval/questions.yaml` · labels: `eval/classification_labels.yaml`, `eval/dedupe_labels.yaml`."]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    results_path = Path(argv[0]) if argv else max((ROOT / "eval" / "results").glob("run-*.jsonl"))
    baseline = Path(argv[1]) if len(argv) > 1 else None
    REPORT.write_text(build(results_path, baseline), encoding="utf-8")
    print(f"Wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
