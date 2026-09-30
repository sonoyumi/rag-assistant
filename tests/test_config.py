import pytest

from rag_assistant.config import load_settings

NAMES = (
    "KB_DIR",
    "DATABASE_PATH",
    "ANSWER_MODE",
    "CLAUDE_EFFORT",
    "CLAUDE_MODEL",
    "ANTHROPIC_API_KEY",
    "TOP_K",
    "CHUNK_CHARS",
    "BOT_TOKEN",
    "ADMIN_IDS",
    "ALLOWED_USER_IDS",
    "QUESTIONS_PER_HOUR",
    "MAX_QUESTION_CHARS",
    "COMPANY_NAME",
    "CONTACT_TEXT",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.setenv(name, "")


def test_defaults_and_auto_mode(monkeypatch):
    s = load_settings()
    assert s.mode == "auto" and not s.use_llm and s.model == "claude-opus-5-5" and s.effort == "medium"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ADMIN_IDS", "1, 2")
    s = load_settings()
    assert s.use_llm and s.admin_ids == {1, 2} and "sk-ant" not in repr(s)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("ANSWER_MODE", "magic", "ANSWER_MODE"),
        ("CLAUDE_EFFORT", "extreme", "CLAUDE_EFFORT"),
        ("TOP_K", "0", "at least 1"),
        ("ADMIN_IDS", "me", "ADMIN_IDS"),
        ("ANSWER_MODE", "llm", "ANTHROPIC_API_KEY"),
    ],
)
def test_bad_values(monkeypatch, name, value, message):
    monkeypatch.setenv(name, value)
    with pytest.raises((ValueError, RuntimeError), match=message):
        load_settings()
