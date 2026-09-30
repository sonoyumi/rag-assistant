import anthropic
import httpx2 as httpx  # the HTTP library anthropic 1.x is built on
import pytest
from conftest import FakeClaude, text_block

from rag_assistant.answer import AnswerError, ClaudeAnswerer, ExtractiveAnswerer, render
from rag_assistant.assistant import Assistant
from rag_assistant.index import Hit

HITS = [
    Hit(1, "faq.md", "FAQ", "Parcheggio", "Il parcheggio costa 12 € al giorno.", 3.0),
    Hit(2, "check-in.md", "Arrivo", "Check-in", "Check-in dalle 14:00.", 2.0),
    Hit(3, "prezzi.txt", "prezzi", "", "Bici: 30 €.", 0.5),
]


def test_request_sends_every_hit_as_a_cited_document():
    request = ClaudeAnswerer(FakeClaude(), company="Hotel Alpina").build_request("Quanto costa?", HITS)
    assert request["model"] == "claude-opus-5-5" and request["output_config"] == {"effort": "medium"}
    assert request["fallbacks"] == "default" and request["betas"] == ["server-side-fallback-2026-07-01"]
    assert "Hotel Alpina" in request["system"] and "not instructions" in request["system"]
    content = request["messages"][0]["content"]
    assert [c["type"] for c in content] == ["document", "document", "document", "text"]
    assert content[0]["citations"] == {"enabled": True} and content[0]["title"] == "FAQ › Parcheggio"
    assert content[0]["source"] == {"type": "text", "media_type": "text/plain", "data": HITS[0].text}
    assert content[-1] == {"type": "text", "text": "Quanto costa?"}


async def test_citations_become_numbered_sources():
    blocks = [
        text_block("Il parcheggio costa "),
        text_block("12 € al giorno", 0, quote="Il parcheggio costa 12 € al giorno."),
        text_block(" e il check-in è "),
        text_block("dalle 14:00", 1),
        text_block(". Ancora "),
        text_block("12 €", 0, 7),  # 7 is not a document we sent: ignored
    ]
    fake = FakeClaude(content=blocks)
    answer = await ClaudeAnswerer(fake).answer("?", HITS)
    assert answer.text == "Il parcheggio costa 12 € al giorno[1] e il check-in è dalle 14:00[2]. Ancora 12 €[1]"
    assert [(s.number, s.label, s.path) for s in answer.sources] == [
        (1, "FAQ › Parcheggio", "faq.md"),
        (2, "Arrivo › Check-in", "check-in.md"),
    ]
    assert answer.sources[0].quote == "Il parcheggio costa 12 € al giorno." and answer.mode == "llm"
    assert answer.usage == {"input_tokens": 900, "output_tokens": 60}


async def test_no_hits_means_no_api_call():
    fake = FakeClaude()
    answer = await ClaudeAnswerer(fake).answer("?", [])
    assert answer.mode == "not_found" and fake.requests == []


async def test_refusal_is_reported():
    answer = await ClaudeAnswerer(FakeClaude(stop_reason="refusal")).answer("?", HITS)
    assert answer.mode == "refusal" and answer.sources == []


def _api_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (_api_error(anthropic.AuthenticationError, 401), "key is invalid"),
        (_api_error(anthropic.RateLimitError, 429), "too many requests"),
        (_api_error(anthropic.InternalServerError, 500), "returned an error"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), "no connection"),
    ],
)
async def test_api_errors_become_readable(error, message):
    with pytest.raises(AnswerError, match=message):
        await ClaudeAnswerer(FakeClaude(error=error)).answer("?", HITS)


async def test_extractive_keeps_only_relevant_passages():
    answer = await ExtractiveAnswerer().answer("?", HITS)
    assert answer.mode == "extractive" and [s.path for s in answer.sources] == ["faq.md", "check-in.md"]
    assert answer.text.startswith("[1] Il parcheggio")
    long_hit = Hit(9, "x.md", "X", "", "parola " * 200, 1.0)
    assert (await ExtractiveAnswerer(max_chars=50).answer("?", [long_hit])).text.endswith("…")


def test_render_without_citations():
    assert render([text_block("Nessuna fonte.")], HITS).sources == []


async def test_assistant_falls_back_to_passages_when_ai_fails(kb):
    fake = FakeClaude(error=_api_error(anthropic.RateLimitError, 429))
    answer = await Assistant(kb, ClaudeAnswerer(fake)).ask("Сколько стоит парковка?")
    assert answer.mode == "extractive" and "too many requests" in answer.note
    assert answer.sources[0].path == "faq_ru.md"
    assert len(fake.requests[0]["messages"][0]["content"]) == 1 + len(kb.search("Сколько стоит парковка?"))
