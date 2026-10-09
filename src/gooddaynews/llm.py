"""Gemini access: structured JSON generation and embeddings, throttled and retried.

Code that needs an LLM takes any object with `generate_json` and `embed`, so tests can
pass a fake instead of calling the API.
"""

import threading
import time
from collections.abc import Iterator
from typing import Protocol, TypeVar

import numpy as np
from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from gooddaynews.settings import Settings, get_settings

T = TypeVar("T", bound=BaseModel)
EMBED_BATCH = 100


class LLM(Protocol):
    def generate_json(self, prompt: str, schema: type[T], *, system: str, fast: bool = False) -> T: ...

    def stream_text(self, prompt: str, *, system: str) -> Iterator[str]: ...

    def embed(self, texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[np.ndarray]: ...


def is_daily_quota(exc: BaseException) -> bool:
    """A per-day free-tier cap: waiting seconds will not help, so move to the next model."""
    return isinstance(exc, errors.ClientError) and getattr(exc, "code", None) == 429 and "PerDay" in str(exc)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, errors.ServerError):
        return True
    return isinstance(exc, errors.ClientError) and getattr(exc, "code", None) == 429 and not is_daily_quota(exc)


def model_list(value: str) -> list[str]:
    return [m.strip() for m in value.split(",") if m.strip()]


_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)


def normalize(vec) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n else v


class GeminiLLM:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        if not self.s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in.")
        self.client = genai.Client(api_key=self.s.gemini_api_key)
        self._lock = threading.Lock()
        self._last_call = 0.0
        self.calls = 0
        self.exhausted: set[str] = set()  # models that hit their daily cap during this run
        self.used: dict[str, int] = {}
        self.empty_responses = 0
        self.last_answer_model: str | None = None  # which model wrote the latest streamed answer
        self._embed_log: list[tuple[float, int]] = []  # (time sent, estimated tokens) for per-minute pacing

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_call + self.s.llm_min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1

    def generate_json(self, prompt: str, schema: type[T], *, system: str, fast: bool = False,
                      models: str | None = None) -> T:
        """Try each configured model in order, skipping any that hit their daily cap.
        `models` (comma-separated) overrides the configured list, e.g. for the evaluation judge."""
        chosen = models or (self.s.triage_model if fast else self.s.chat_model)
        models = [m for m in model_list(chosen) if m not in self.exhausted]
        if not models:
            raise RuntimeError("every configured Gemini model has hit its daily free-tier limit")
        for model in models:
            try:
                result = self._generate(model, prompt, schema, system)
                self.used[model] = self.used.get(model, 0) + 1
                return result
            except errors.ClientError as exc:
                if not is_daily_quota(exc):
                    raise
                self.exhausted.add(model)
                if model == models[-1]:
                    raise
        raise AssertionError("unreachable")

    @_retry
    def _generate(self, model: str, prompt: str, schema: type[T], system: str) -> T:
        self._throttle()
        resp = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.2,
            ),
        )
        if isinstance(resp.parsed, schema):
            return resp.parsed
        return schema.model_validate_json(resp.text or "")

    def stream_text(self, prompt: str, *, system: str) -> Iterator[str]:
        """Stream a plain-text answer from the answer models, falling back when one hits its daily cap.
        Fallback only happens before the first chunk, so the user never sees two answers mixed."""
        models = [m for m in model_list(self.s.answer_model) if m not in self.exhausted]
        if not models:
            raise RuntimeError("every configured Gemini model has hit its daily free-tier limit")
        for model in models:
            try:
                first, rest = self._open_stream(model, prompt, system)
            except errors.ClientError as exc:
                if not is_daily_quota(exc):
                    raise
                self.exhausted.add(model)
                if model == models[-1]:
                    raise
                continue
            self.used[model] = self.used.get(model, 0) + 1
            self.last_answer_model = model
            if not first:
                # The model finished without any visible text (it can happen after long "thinking").
                self.empty_responses += 1
                continue
            yield first
            for chunk in rest:
                if chunk.text:
                    yield chunk.text
            return
        raise RuntimeError("no model returned an answer")

    @_retry
    def _open_stream(self, model: str, prompt: str, system: str):
        self._throttle()
        thinking = (
            types.ThinkingConfig(thinking_level=self.s.answer_thinking.upper()) if self.s.answer_thinking else None
        )
        stream = iter(self.client.models.generate_content_stream(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.2, thinking_config=thinking),
        ))
        for chunk in stream:  # errors such as quota limits surface on the first chunk
            if chunk.text:
                return chunk.text, stream
        return "", stream

    def _pace_embedding(self, tokens: int, count: int) -> None:
        """Wait until sending `count` more texts (`tokens` tokens) keeps the last 60 seconds under both
        per-minute limits. The free tier counts every text in a batch as one request (100 a minute)."""
        while True:
            now = time.monotonic()
            self._embed_log = [e for e in self._embed_log if now - e[0] < 60]
            used_tokens = sum(e[1] for e in self._embed_log)
            used_texts = sum(e[2] for e in self._embed_log)
            if not self._embed_log or (used_tokens + tokens <= self.s.embed_tokens_per_minute
                                       and used_texts + count <= self.s.embed_texts_per_minute):
                self._embed_log.append((now, tokens, count))
                return
            time.sleep(60 - (now - self._embed_log[0][0]) + 0.5)

    @_retry
    def _embed_batch(self, texts: list[str], task: str) -> list[np.ndarray]:
        self._pace_embedding(sum(estimate_tokens(t) for t in texts), len(texts))
        self._throttle()
        resp = self.client.models.embed_content(
            model=self.s.embed_model,
            contents=texts,
            config=types.EmbedContentConfig(task_type=task, output_dimensionality=self.s.embed_dim),
        )
        # Reduced-size Gemini embeddings are not unit length; normalise for cosine similarity.
        return [normalize(e.values) for e in resp.embeddings]

    def embed(self, texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for batch in embedding_batches(texts, self.s.embed_batch_tokens, self.s.embed_texts_per_minute):
            out.extend(self._embed_batch(batch, task))
        return out


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def embedding_batches(texts: list[str], max_tokens: int, max_items: int = EMBED_BATCH) -> list[list[str]]:
    """Split texts into requests of at most `max_items` texts (and EMBED_BATCH) and about `max_tokens` tokens."""
    max_items = min(max_items, EMBED_BATCH)
    batches, current, size = [], [], 0
    for t in texts:
        n = estimate_tokens(t)
        if current and (len(current) == max_items or size + n > max_tokens):
            batches.append(current)
            current, size = [], 0
        current.append(t)
        size += n
    if current:
        batches.append(current)
    return batches
