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


def test_embedding_batches_respect_token_budget():
    from gooddaynews.llm import EMBED_BATCH, embedding_batches, estimate_tokens

    texts = ["x" * 4000] * 10  # about 1,000 tokens each
    batches = embedding_batches(texts, max_tokens=3000)
    assert [len(b) for b in batches] == [2, 2, 2, 2, 2]
    assert all(sum(estimate_tokens(t) for t in b) <= 3000 for b in batches)
    assert embedding_batches(["a"] * (EMBED_BATCH + 1), 10**6)[1] == ["a"]
    assert embedding_batches([], 100) == []


def test_embedding_pacing_waits_when_minute_budget_is_used(monkeypatch):
    import gooddaynews.llm as llm_mod

    clock = {"t": 1000.0}
    slept = []
    monkeypatch.setattr(llm_mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: (slept.append(s), clock.update(t=clock["t"] + s)))
    llm = GeminiLLM(Settings(gemini_api_key="test", embed_tokens_per_minute=10000))
    llm._pace_embedding(8000)
    assert slept == []
    llm._pace_embedding(5000)  # 13,000 in one minute is over the limit: wait for the first batch to age out
    assert len(slept) == 1 and 60 <= slept[0] <= 61


class _Chunk:
    def __init__(self, text):
        self.text = text


def test_stream_moves_to_next_model_when_one_returns_nothing(monkeypatch):
    llm = GeminiLLM(Settings(gemini_api_key="test", answer_model="empty-model, good-model"))
    replies = {"empty-model": ("", iter([])), "good-model": ("Hello", iter([_Chunk(" world")]))}
    monkeypatch.setattr(llm, "_open_stream", lambda model, prompt, system: replies[model])
    assert "".join(llm.stream_text("p", system="s")) == "Hello world"
    assert llm.empty_responses == 1


def test_stream_falls_back_on_daily_cap(monkeypatch):
    llm = GeminiLLM(Settings(gemini_api_key="test", answer_model="capped, good"))

    def open_stream(model, prompt, system):
        if model == "capped":
            raise errors.ClientError(429, DAILY)
        return "ok", iter([])

    monkeypatch.setattr(llm, "_open_stream", open_stream)
    assert "".join(llm.stream_text("p", system="s")) == "ok"
    assert "capped" in llm.exhausted


def test_all_models_capped_raises(monkeypatch):
    llm, _ = make_llm(monkeypatch, lambda m: (_ for _ in ()).throw(errors.ClientError(429, DAILY)))
    with pytest.raises(errors.ClientError):
        llm.generate_json("p", TriageResult, system="s")
    with pytest.raises(RuntimeError, match="daily free-tier limit"):
        llm.generate_json("p", TriageResult, system="s")
