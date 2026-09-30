"""Settings from environment variables (.env in the project folder)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODES = ("auto", "llm", "extractive")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Settings:
    kb_dir: Path
    database_path: Path
    company: str = "the company"
    contact: str = ""
    mode: str = "auto"  # auto = AI answers when ANTHROPIC_API_KEY is set, otherwise passages
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    top_k: int = 5
    chunk_chars: int = 1200
    bot_token: str = field(default="", repr=False)
    admin_ids: frozenset[int] = frozenset()
    allowed_user_ids: frozenset[int] = frozenset()  # empty = everyone may ask
    questions_per_hour: int = 20
    max_question_chars: int = 1000
    has_api_key: bool = False

    @property
    def use_llm(self) -> bool:
        return self.mode == "llm" or (self.mode == "auto" and self.has_api_key)


def _int(name: str, default: int, low: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < low:
        raise ValueError(f"{name} must be at least {low}")
    return value


def _ids(name: str) -> frozenset[int]:
    raw = os.getenv(name, "")
    try:
        return frozenset(int(part) for part in raw.replace(" ", "").split(",") if part)
    except ValueError:
        raise ValueError(f"{name} must be a comma-separated list of integers, got {raw!r}") from None


def _path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, "").strip() or default)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    mode = (os.getenv("ANSWER_MODE", "").strip() or "auto").lower()
    if mode not in MODES:
        raise ValueError(f"ANSWER_MODE must be one of {', '.join(MODES)}, got {mode!r}")
    effort = (os.getenv("CLAUDE_EFFORT", "").strip() or "medium").lower()
    if effort not in EFFORTS:
        raise ValueError(f"CLAUDE_EFFORT must be one of {', '.join(EFFORTS)}, got {effort!r}")
    has_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    if mode == "llm" and not has_key:
        raise RuntimeError("ANSWER_MODE=llm needs ANTHROPIC_API_KEY in .env")
    return Settings(
        kb_dir=_path("KB_DIR", "knowledge"),
        database_path=_path("DATABASE_PATH", "data/kb.db"),
        company=os.getenv("COMPANY_NAME", "").strip() or "the company",
        contact=os.getenv("CONTACT_TEXT", "").strip(),
        mode=mode,
        model=os.getenv("CLAUDE_MODEL", "").strip() or "claude-opus-5-5",
        effort=effort,
        top_k=_int("TOP_K", 5),
        chunk_chars=_int("CHUNK_CHARS", 1200, low=200),
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        admin_ids=_ids("ADMIN_IDS"),
        allowed_user_ids=_ids("ALLOWED_USER_IDS"),
        questions_per_hour=_int("QUESTIONS_PER_HOUR", 20),
        max_question_chars=_int("MAX_QUESTION_CHARS", 1000, low=20),
        has_api_key=has_key,
    )
