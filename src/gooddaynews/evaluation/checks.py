"""Automatic checks for one evaluated chat answer. Pure functions, no LLM or database calls."""

import re
from datetime import date

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CITATION_RE = re.compile(r"\[\d+\]")


def numbers(text: str) -> set[str]:
    """Numbers in a text, normalised so '6,719', '06' and '6719.0' compare sensibly."""
    out = set()
    for n in _NUMBER_RE.findall(_CITATION_RE.sub(" ", text)):
        n = n.replace(",", "").rstrip(".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n.lstrip("0") or "0")
    return out


def unsupported_numbers(answer: str, context: str, as_of: date) -> list[str]:
    """Numbers in the answer that appear nowhere in the sources it was given (possible invented figures).
    The current year is allowed because answers state dates. Rounded figures show up here too, so these
    are flagged for review rather than counted as errors outright."""
    allowed = numbers(context) | {str(as_of.year), str(as_of.day)}
    return sorted(numbers(answer) - allowed, key=lambda x: (len(x), x))


def outcome_ok(expect: str, kind: str) -> bool:
    if expect == "answer_or_refuse":
        return kind in ("answer", "refused")
    return {"answer": "answer", "refuse": "refused", "out_of_scope": "out_of_scope"}[expect] == kind


def _norm(text: str) -> str:
    return text.lower().replace(",", "")


def mentioned(expected: str | list[str], text: str) -> bool:
    """A required fact; a list means any of the alternatives counts (e.g. [bench, desk])."""
    options = expected if isinstance(expected, list) else [expected]
    return any(_norm(str(o)) in _norm(text) for o in options)


def check(item: dict, result: dict, context: str, as_of: date) -> dict:
    """All automatic checks for one question. A check is None when it doesn't apply."""
    kind, text, cited = result["kind"], result["text"], result["cited"]
    answered = kind == "answer"
    c: dict[str, object] = {"outcome": outcome_ok(item["expect"], kind)}

    c["cites_expected"] = bool(set(item["cite_any"]) & {x["id"] for x in cited}) if "cite_any" in item and answered else None
    c["has_citations"] = bool(cited) if answered else None
    c["mentions"] = all(mentioned(m, text) for m in item["mention"]) if "mention" in item and answered else None
    c["missing_mentions"] = ([" or ".join(m) if isinstance(m, list) else m
                              for m in item.get("mention", []) if not mentioned(m, text)] if answered else [])
    c["avoids_forbidden"] = (not any(f.lower() in text.lower() for f in item["not_mention"])
                             if "not_mention" in item else None)

    if "cited_country" in item and answered and cited:
        c["country"] = all(x["country"] == item["cited_country"] for x in cited)
    else:
        c["country"] = None
    if "cited_from" in item and answered and cited:
        start = date.fromisoformat(str(item["cited_from"]))
        end = date.fromisoformat(str(item.get("cited_to", as_of)))
        c["recency"] = all(x["date"] and start <= date.fromisoformat(x["date"]) <= end for x in cited)
    else:
        c["recency"] = None

    c["unsupported_numbers"] = unsupported_numbers(text, context, as_of) if answered else []
    return c


def passed(c: dict) -> bool:
    """An item passes when every applicable check passes. Unsupported numbers are reviewed, not failed."""
    keys = ("outcome", "cites_expected", "has_citations", "mentions", "avoids_forbidden", "country", "recency")
    return all(c[k] is not False for k in keys if k in c)
