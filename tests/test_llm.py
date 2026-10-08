import pytest
from google.genai import errors

from gooddaynews.llm import GeminiLLM, is_daily_quota
from gooddaynews.process.schemas import TriageResult
from gooddaynews.settings import Settings

DAILY = {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED",
                   "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
PER_MINUTE = {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED",
                        "details": [{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}]}]}}


def make_llm(monkeypatch, behaviour):
    """GeminiLLM whose _generate is replaced: behaviour(model) returns a result or raises."""
    llm = GeminiLLM(Settings(gemini_api_key="test", chat_model="model-a, model-b", triage_model="lite"))
    calls = []

    def fake_generate(model, prompt, schema, system):
        calls.append(model)
        return behaviour(model)

    monkeypatch.setattr(llm, "_generate", fake_generate)
    return llm, calls


def test_daily_quota_is_detected():
    assert is_daily_quota(errors.ClientError(429, DAILY))
    assert not is_daily_quota(errors.ClientError(429, PER_MINUTE))
    assert not is_daily_quota(errors.ClientError(403, {"error": {"code": 403, "message": "denied"}}))


def test_falls_back_to_next_model_when_daily_cap_is_hit(monkeypatch):
    def behaviour(model):
        if model == "model-a":
            raise errors.ClientError(429, DAILY)
        return TriageResult(items=[])

    llm, calls = make_llm(monkeypatch, behaviour)
    llm.generate_json("p", TriageResult, system="s")
    llm.generate_json("p", TriageResult, system="s")
    # The capped model is skipped for the rest of the run.
    assert calls == ["model-a", "model-b", "model-b"]
    assert llm.used == {"model-b": 2}


def test_other_errors_are_not_masked_by_fallback(monkeypatch):
    def behaviour(model):
        raise errors.ClientError(403, {"error": {"code": 403, "message": "denied"}})

    llm, calls = make_llm(monkeypatch, behaviour)
    with pytest.raises(errors.ClientError):
        llm.generate_json("p", TriageResult, system="s")
    assert calls == ["model-a"]


def test_all_models_capped_raises(monkeypatch):
    llm, _ = make_llm(monkeypatch, lambda m: (_ for _ in ()).throw(errors.ClientError(429, DAILY)))
    with pytest.raises(errors.ClientError):
        llm.generate_json("p", TriageResult, system="s")
    with pytest.raises(RuntimeError, match="daily free-tier limit"):
        llm.generate_json("p", TriageResult, system="s")
