"""Shared fixtures: the example knowledge base indexed into a temporary database,
settings for tests and a fake Claude client that records requests."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from rag_assistant.config import Settings
from rag_assistant.index import KnowledgeBase

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "kb"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        kb_dir=EXAMPLES,
        database_path=tmp_path / "kb.db",
        company="Hotel Alpina",
        contact="reception@hotel-alpina.example",
        mode="extractive",
        bot_token="42:TEST",
        admin_ids=frozenset({1}),
        questions_per_hour=3,
        max_question_chars=200,
    )


@pytest.fixture
def kb(settings):
    base = KnowledgeBase(settings.database_path)
    base.index_folder(EXAMPLES)
    yield base
    base.close()


def text_block(text: str, *citations: int, quote: str = "") -> SimpleNamespace:
    cites = [
        SimpleNamespace(type="char_location", document_index=i, cited_text=quote or f"quote {i}") for i in citations
    ]
    return SimpleNamespace(type="text", text=text, citations=cites or None)


class FakeClaude:
    """Mimics `AsyncAnthropic().beta.messages.create` and records every request."""

    def __init__(self, content=None, stop_reason: str = "end_turn", error: Exception | None = None) -> None:
        self.requests: list[dict] = []
        self.content = content or []
        self.stop_reason = stop_reason
        self.error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(
            content=self.content,
            stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=900, output_tokens=60),
        )
