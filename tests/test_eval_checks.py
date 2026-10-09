from datetime import date

from gooddaynews.evaluation.checks import check, numbers, outcome_ok, passed, unsupported_numbers

AS_OF = date(2026, 10, 9)


def result(kind="answer", text="", cited=None):
    return {"kind": kind, "text": text, "cited": cited or []}


def cite(id, country="IN", day="2026-10-08"):
    return {"id": id, "country": country, "date": day}


def test_numbers_normalise_commas_zeros_and_ignore_citations():
    assert numbers("6,719 km on 08 Oct [2], about 3.50 times") == {"6719", "8", "3.5"}


def test_invented_numbers_are_flagged_but_years_and_today_allowed():
    context = "The turtle travelled 6,719 km over 271 days."
    assert unsupported_numbers("It travelled 6719 km in 2026 [1].", context, AS_OF) == []
    assert unsupported_numbers("It travelled 6,719 km over 300 days.", context, AS_OF) == ["300"]


def test_outcomes():
    assert outcome_ok("refuse", "refused") and not outcome_ok("refuse", "answer")
    assert outcome_ok("answer_or_refuse", "refused") and outcome_ok("answer_or_refuse", "answer")
    assert not outcome_ok("out_of_scope", "answer")


def test_factual_answer_checks():
    item = {"expect": "answer", "cite_any": [27], "mention": ["6,719"]}
    good = check(item, result(text="It travelled 6719 km [1].", cited=[cite(27)]), "6,719 km", AS_OF)
    assert passed(good) and good["mentions"] and good["cites_expected"]

    wrong_story = check(item, result(text="It travelled 6719 km [1].", cited=[cite(13)]), "6,719", AS_OF)
    assert not passed(wrong_story) and wrong_story["cites_expected"] is False

    uncited = check(item, result(text="It travelled 6719 km."), "6,719", AS_OF)
    assert not passed(uncited) and uncited["has_citations"] is False


def test_country_and_recency_apply_to_every_cited_story():
    item = {"expect": "answer", "cited_country": "IN", "cited_from": "2026-10-08", "cited_to": "2026-10-08"}
    ok = check(item, result(text="x [1]", cited=[cite(1)]), "", AS_OF)
    assert ok["country"] and ok["recency"]
    bad = check(item, result(text="x [1][2]", cited=[cite(1), cite(2, "GB", "2026-10-06")]), "", AS_OF)
    assert bad["country"] is False and bad["recency"] is False and not passed(bad)


def test_refusal_items_only_check_the_outcome():
    item = {"expect": "refuse"}
    c = check(item, result(kind="refused", text="I couldn't find enough reliable reporting..."), "", AS_OF)
    assert passed(c) and c["cites_expected"] is None and c["unsupported_numbers"] == []
    assert not passed(check(item, result(kind="answer", text="RBI cut rates [1]", cited=[cite(1)]), "", AS_OF))


def test_forbidden_phrases():
    item = {"expect": "answer", "not_mention": ["% confident"]}
    assert not passed(check(item, result(text="I am 90% confident [1]", cited=[cite(1)]), "", AS_OF))


def test_report_metrics_combine_checks_judge_and_outcomes():
    from gooddaynews.evaluation.report import chat_metrics

    def r(id, category, expect, kind, checks=None, judge=None, passed=True):
        base = {"outcome": True, "cites_expected": None, "has_citations": None, "mentions": None,
                "recency": None, "country": None}
        return {"id": id, "category": category, "expect": expect, "kind": kind, "seconds": 10,
                "checks": base | (checks or {}), "judge": judge, "passed": passed}

    results = [
        r("A1", "factual", "answer", "answer", {"cites_expected": True, "has_citations": True, "mentions": True},
          {"accuracy": "supported", "citations": "correct", "premise": "not_applicable"}),
        r("A2", "factual", "answer", "answer", {"cites_expected": False, "has_citations": True, "mentions": True},
          {"accuracy": "partly_supported", "citations": "partly_correct", "premise": "not_applicable"}, passed=False),
        r("A3", "factual", "answer", "refused", {"outcome": False}, passed=False),
        r("N1", "unanswerable", "refuse", "refused"),
        r("O1", "out_of_scope", "out_of_scope", "out_of_scope"),
        r("X1", "trap", "answer_or_refuse", "answer", judge={"accuracy": "supported", "citations": "correct",
                                                             "premise": "accepted"}, passed=False),
    ]
    m = chat_metrics(results)
    assert m["accuracy_judge"] == 0.75 and m["cites_expected"] == (1, 2)
    assert m["false_refusals"] == 1 and m["answerable"] == 3
    assert m["unanswerable_handling"] == (2, 3)  # the trap that accepted its premise counts against
    assert m["passed"] == 3


def test_question_set_is_well_formed():
    from gooddaynews.evaluation.run import load_questions

    as_of, questions = load_questions()
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)) == 30
    assert all(q["expect"] in ("answer", "refuse", "out_of_scope", "answer_or_refuse") for q in questions)
    assert all(q.get("premise") for q in questions if q["category"] == "trap")


def test_mention_alternatives():
    item = {"expect": "answer", "mention": ["1,500", ["bench", "desk"]]}
    assert check(item, result(text="1500 volunteers; plastic became school desks [1]", cited=[cite(38)]), "", AS_OF)["mentions"]
    missing = check(item, result(text="1500 volunteers [1]", cited=[cite(38)]), "", AS_OF)
    assert missing["missing_mentions"] == ["bench or desk"]
