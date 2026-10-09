"""LLM-as-judge: grades an answer against the exact sources it was given."""

from typing import Literal

from pydantic import BaseModel, Field


class Judgement(BaseModel):
    accuracy: Literal["supported", "partly_supported", "unsupported"] = Field(
        description="supported: every factual claim is backed by the sources; partly_supported: minor overstatement "
                    "or one claim not in the sources; unsupported: a main claim is missing from or contradicts them")
    citations: Literal["correct", "partly_correct", "incorrect", "none"] = Field(
        description="whether each [n] points to a source that actually supports the sentence it is attached to")
    premise: Literal["corrected", "accepted", "not_applicable"] = Field(
        description="for a question with a false premise: corrected if the answer does not go along with it")
    unsupported_claims: list[str] = Field(description="claims in the answer not supported by the sources; [] if none")
    notes: str = Field(description="one short sentence explaining the grades")


JUDGE_SYSTEM = """You are a strict grader for a news assistant that must answer ONLY from the numbered sources it was
given. You see the question, the sources and the answer. Judge only against the sources, not your own knowledge:
a claim that is true in the real world but absent from the sources is unsupported.
Paraphrase and simple rounding ("over 1,200" for "1,203") count as supported.
If a false premise is described, decide whether the answer corrected it or went along with it."""


def judge_prompt(question: str, sources: str, answer: str, premise: str | None) -> str:
    false_premise = f"\nFalse premise in the question: {premise}\n" if premise else ""
    return f"""Question: {question}
{false_premise}
Sources given to the assistant:
{sources}

Assistant's answer:
{answer}"""


ACCURACY_POINTS = {"supported": 1.0, "partly_supported": 0.5, "unsupported": 0.0}
CITATION_POINTS = {"correct": 1.0, "partly_correct": 0.5, "incorrect": 0.0, "none": 0.0}
