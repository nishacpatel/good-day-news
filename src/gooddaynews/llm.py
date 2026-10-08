"""Gemini access: structured JSON generation and embeddings, throttled and retried.

Code that needs an LLM takes any object with `generate_json` and `embed`, so tests can
pass a fake instead of calling the API.
"""

import threading
import time
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

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_call + self.s.llm_min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1

    def generate_json(self, prompt: str, schema: type[T], *, system: str, fast: bool = False) -> T:
        """Try each configured model in order, skipping any that hit their daily cap."""
        models = [m for m in model_list(self.s.triage_model if fast else self.s.chat_model) if m not in self.exhausted]
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

    @_retry
    def _embed_batch(self, texts: list[str], task: str) -> list[np.ndarray]:
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
        for i in range(0, len(texts), EMBED_BATCH):
            out.extend(self._embed_batch(texts[i : i + EMBED_BATCH], task))
        return out
