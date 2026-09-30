"""The Telegram bot through the real aiogram Dispatcher (network replaced by a recorder), and the CLI."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendChatAction, SendMessage
from aiogram.types import Chat, Message, Update, User
from conftest import FakeClaude, text_block

from rag_assistant import bot as bot_module
from rag_assistant import cli, texts
from rag_assistant.answer import Answer, ClaudeAnswerer, ExtractiveAnswerer, Source
from rag_assistant.assistant import Assistant
from rag_assistant.bot import build_dispatcher
from rag_assistant.ratelimit import RateLimiter

USER = User(id=100, is_bot=False, first_name="Anna")
ADMIN = User(id=1, is_bot=False, first_name="Owner")


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - signature set by aiogram
        self.calls.append(method)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        pass

    def texts(self):
        return [c.text for c in self.calls if isinstance(c, SendMessage)]


@pytest.fixture
def make_bot(kb, settings):
    def factory(answerer=None, **overrides):
        bot_module.router._parent_router = None
        session = RecordingSession()
        bot = Bot("42:TEST", session=session)
        assistant = Assistant(kb, answerer or ExtractiveAnswerer())
        s = replace(settings, **overrides)
        dp = build_dispatcher(s, assistant, RateLimiter(s.questions_per_hour))
        return bot, dp, session

    yield factory
    bot_module.router._parent_router = None


async def say(bot, dp, text, user=USER):
    message = Message(
        message_id=1, date=datetime.now(UTC), chat=Chat(id=user.id, type="private"), from_user=user, text=text
    )
    await dp.feed_update(bot, Update(update_id=1, message=message))


async def test_question_gets_answer_with_sources(make_bot):
    bot, dp, session = make_bot()
    await say(bot, dp, "/start")
    assert "Hotel Alpina" in session.texts()[-1]
    await say(bot, dp, "Quanto costa la tassa di soggiorno?")
    assert any(isinstance(c, SendChatAction) for c in session.calls)
    reply = session.texts()[-1]
    assert "2,50 €" in reply and "<b>Источники:</b>" in reply and "ospiti/check-in.md" in reply


async def test_ai_answer_through_the_bot(make_bot):
    fake = FakeClaude(content=[text_block("Il parcheggio costa "), text_block("12 € al giorno", 0)])
    bot, dp, session = make_bot(ClaudeAnswerer(fake))
    await say(bot, dp, "Сколько стоит парковка?")
    assert session.texts()[-1].startswith("Il parcheggio costa 12 € al giorno[1]")
    assert "faq_ru.md" in session.texts()[-1]


async def test_unknown_question_offers_contact(make_bot):
    bot, dp, session = make_bot()
    await say(bot, dp, "C'è una piscina olimpionica?")
    assert "нет ответа" in session.texts()[-1] and "reception@hotel-alpina.example" in session.texts()[-1]


async def test_access_length_and_rate_limits(make_bot):
    bot, dp, session = make_bot(allowed_user_ids=frozenset({555}))
    await say(bot, dp, "Wi-Fi?")
    assert "только для сотрудников" in session.texts()[-1]
    await say(bot, dp, "Wi-Fi?", user=ADMIN)  # admins are always allowed
    assert "Alpina-Guest" in session.texts()[-1]

    bot, dp, session = make_bot()
    await say(bot, dp, "x" * 300)
    assert "слишком длинный" in session.texts()[-1]
    for _ in range(3):
        await say(bot, dp, "Wi-Fi?")
    await say(bot, dp, "Wi-Fi?")
    assert "Слишком много вопросов" in session.texts()[-1]
    await say(bot, dp, "Wi-Fi?", user=ADMIN)  # no limit for admins
    assert "Alpina-Guest" in session.texts()[-1]


async def test_admin_commands(make_bot):
    bot, dp, session = make_bot()
    await say(bot, dp, "/reindex")
    assert "только администратору" in session.texts()[-1]
    await say(bot, dp, "/reindex", user=ADMIN)
    assert "без изменений 5" in session.texts()[-1]
    await say(bot, dp, "/stats", user=ADMIN)
    assert "Документов: 5, фрагментов: 12" in session.texts()[-1]
    await say(bot, dp, "/help", user=ADMIN)
    assert "/reindex" in session.texts()[-1]


def test_rate_limiter_window():
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    assert limiter.check(1) == 0 and limiter.check(1) == 0
    assert limiter.check(1) == 3600
    assert limiter.check(2) == 0  # other users are independent
    now[0] = 3600.5
    assert limiter.check(1) == 0


def test_long_answers_are_split_for_telegram():
    parts = texts.split_message("\n\n".join(["a" * 3000, "b" * 3000, "c" * 9000]))
    assert all(len(p) <= texts.TELEGRAM_LIMIT for p in parts) and "".join(parts).count("c") == 9000
    html = texts.format_html(Answer("<b>x</b>", [Source(1, "A & B", "a.md")]))
    assert html.startswith("&lt;b&gt;x&lt;/b&gt;") and "A &amp; B" in html  # user and document text is escaped
    degraded = texts.format_plain(Answer("t", mode="extractive", note="no connection"))
    assert "ИИ сейчас недоступен (no connection)" in degraded


def test_cli_index_search_ask(settings, capsys):
    assert cli.run(["index"], settings=settings) == 0
    assert "Новых: 5" in capsys.readouterr().out
    assert cli.run(["index"], settings=settings) == 0
    assert "без изменений: 5" in capsys.readouterr().out
    assert cli.run(["search", "noleggio bici"], settings=settings) == 0
    assert "prezzi.txt" in capsys.readouterr().out
    assert cli.run(["ask", "Can I smoke on the balcony?"], settings=settings) == 0
    out = capsys.readouterr().out
    assert "150 EUR" in out and "house-rules.pdf" in out
    assert cli.run(["stats"], settings=settings) == 0
    assert "Документов: 5" in capsys.readouterr().out


def test_cli_errors(settings, tmp_path, capsys):
    assert cli.run(["index"], settings=replace(settings, kb_dir=tmp_path / "nope")) == 2
    assert cli.run(["bot"], settings=replace(settings, bot_token="")) == 2
    err = capsys.readouterr().err
    assert "не найдена" in err and "BOT_TOKEN" in err
