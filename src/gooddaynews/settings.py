"""Settings loaded from .env and the YAML files in config/."""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env")


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    chat_model: str = field(default_factory=lambda: os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash-lite,gemini-3-flash-preview,gemini-3.1-flash-lite"))
    embed_model: str = field(default_factory=lambda: os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001"))
    triage_model: str = field(default_factory=lambda: os.getenv("GEMINI_TRIAGE_MODEL", "gemini-3.1-flash-lite,gemini-3.5-flash-lite"))
    embed_dim: int = field(default_factory=lambda: int(os.getenv("EMBED_DIM", "768")))
    llm_min_interval: float = field(default_factory=lambda: float(os.getenv("LLM_MIN_INTERVAL_SECONDS", "4")))
    lookback_hours: int = field(default_factory=lambda: int(os.getenv("LOOKBACK_HOURS", "48")))
    fetch_timeout: int = field(default_factory=lambda: int(os.getenv("FETCH_TIMEOUT_SECONDS", "20")))
    user_agent: str = field(
        default_factory=lambda: os.getenv("USER_AGENT", "ConstructiveNewsAI/0.1 (student capstone project)")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
