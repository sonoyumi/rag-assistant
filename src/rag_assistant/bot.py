"""Telegram bot: a question in, an answer with sources out."""

from __future__ import annotations

import asyncio
import logging
import math

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from rag_assistant import texts
from rag_assistant.assistant import Assistant
from rag_assistant.config import Settings
from rag_assistant.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

router = Router(name="kb")
# Company documents may be internal: answer in private chats only.
router.message.filter(F.chat.type == ChatType.PRIVATE)


def _is_admin(settings: Settings, message: Message) -> bool:
    return message.from_user is not None and message.from_user.id in settings.admin_ids


def _allowed(settings: Settings, message: Message) -> bool:
    if message.from_user is None:
        return False
    return not settings.allowed_user_ids or message.from_user.id in settings.allowed_user_ids | settings.admin_ids


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings) -> None:
    if not _allowed(settings, message):
        await message.answer(texts.NOT_ALLOWED)
        return
    await message.answer(texts.START.format(company=settings.company))


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    await message.answer(texts.HELP + (texts.ADMIN_HELP if _is_admin(settings, message) else ""))


@router.message(Command("stats"))
async def cmd_stats(message: Message, settings: Settings, assistant: Assistant) -> None:
    if not _is_admin(settings, message):
        await message.answer(texts.ADMIN_ONLY)
        return
    s = await asyncio.to_thread(assistant.kb.stats)
    mode = f"ИИ ({settings.model}, effort {settings.effort})" if settings.use_llm else "фрагменты без ИИ"
    await message.answer(
        f"📚 Документов: {s['documents']}, фрагментов: {s['chunks']}\n"
        f"Последняя индексация: {s['last_indexed']}\nРежим ответов: {mode}"
    )


@router.message(Command("reindex"))
async def cmd_reindex(message: Message, settings: Settings, assistant: Assistant) -> None:
    if not _is_admin(settings, message):
        await message.answer(texts.ADMIN_ONLY)
        return
    try:
        report = await asyncio.to_thread(assistant.kb.index_folder, settings.kb_dir, max_chars=settings.chunk_chars)
    except FileNotFoundError:
        await message.answer(f"Папка с документами не найдена: {settings.kb_dir}")
        return
    failed = "".join(f"\n❌ {path}: {reason}" for path, reason in report.failed)
    await message.answer(
        f"✅ Индекс обновлён: новых {report.added}, изменённых {report.updated}, удалённых {report.removed}, "
        f"без изменений {report.unchanged}. Фрагментов: {report.chunks}{failed}"
    )


@router.message(F.text & ~F.text.startswith("/"))
async def on_question(
    message: Message, bot: Bot, settings: Settings, assistant: Assistant, limiter: RateLimiter
) -> None:
    if not _allowed(settings, message):
        await message.answer(texts.NOT_ALLOWED)
        return
    question = (message.text or "").strip()
    if len(question) > settings.max_question_chars:
        await message.answer(texts.TOO_LONG.format(limit=settings.max_question_chars))
        return
    if not _is_admin(settings, message):
        wait = limiter.check(message.from_user.id)
        if wait:
            await message.answer(texts.RATE_LIMITED.format(minutes=max(1, math.ceil(wait / 60))))
            return
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    answer = await assistant.ask(question)
    for part in texts.split_message(texts.format_html(answer, settings.contact)):
        await message.answer(part, disable_web_page_preview=True)


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(texts.ONLY_TEXT)


def build_dispatcher(settings: Settings, assistant: Assistant, limiter: RateLimiter | None = None) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    dp["settings"] = settings
    dp["assistant"] = assistant
    dp["limiter"] = limiter or RateLimiter(settings.questions_per_hour)
    return dp
