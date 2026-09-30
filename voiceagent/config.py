"""Central configuration, loaded from .env and the environment."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    api_key: str = field(default_factory=lambda: _env("GOOGLE_API_KEY"))
    model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.5-flash"))
    # Tried in order when the primary model is throttled or unavailable.
    fallbacks: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            m.strip()
            for m in _env("GEMINI_FALLBACKS", "gemini-3.7-flash,gemini-3.8-flash").split(",")
            if m.strip()
        )
    )
    name: str = field(default_factory=lambda: _env("AGENT_NAME", "Hudu"))
    stt_backend: str = field(default_factory=lambda: _env("STT_BACKEND", "gemini").lower())
    gcp_project: str = field(default_factory=lambda: _env("GOOGLE_CLOUD_PROJECT"))
    gcp_credentials: str = field(default_factory=lambda: _env("GOOGLE_APPLICATION_CREDENTIALS"))
    wake_word: str = field(default_factory=lambda: _env("WAKE_WORD", "jarvis"))
    wake_word_required: bool = field(default_factory=lambda: _env_bool("WAKE_WORD_REQUIRED", True))
    tts_enabled: bool = field(default_factory=lambda: _env_bool("TTS_ENABLED", True))
    tts_rate: int = field(default_factory=lambda: _env_int("TTS_RATE", 175))
    tts_voice_index: int = field(default_factory=lambda: _env_int("TTS_VOICE_INDEX", 0))
    max_record_seconds: int = field(default_factory=lambda: _env_int("MAX_RECORD_SECONDS", 20))
    history_turns: int = field(default_factory=lambda: _env_int("HISTORY_TURNS", 12))
    sample_rate: int = 16000
    block_ms: int = 20
    silence_seconds: float = 0.9

    def require_api_key(self) -> None:
        if not self.api_key:
            sys.exit(
                "GOOGLE_API_KEY is missing.\n"
                "Copy .env.example to .env and paste your key from "
                "https://aistudio.google.com/apikey"
            )

    def model_chain(self) -> list[str]:
        """Primary model first, then any fallbacks, with no duplicates."""
        chain = [self.model, *self.fallbacks]
        seen: set[str] = set()
        return [m for m in chain if not (m in seen or seen.add(m))]


CONFIG = Config()
