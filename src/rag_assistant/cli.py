"""Command line.

rag-assistant index [--rebuild]        read the documents folder into the search index
rag-assistant search "question"        show what search finds (no AI, free)
rag-assistant ask "question" [--no-llm]
rag-assistant stats
rag-assistant bot                      run the Telegram bot
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from collections.abc import Sequence

from rag_assistant import __version__, texts
from rag_assistant.answer import Answerer, ClaudeAnswerer, ExtractiveAnswerer
from rag_assistant.assistant import Assistant
from rag_assistant.config import Settings, load_settings
from rag_assistant.index import KnowledgeBase


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rag-assistant", description="Answers from your documents, with sources")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    idx = sub.add_parser("index", help="index the documents folder (KB_DIR)")
    idx.add_argument("--rebuild", action="store_true", help="drop the index and read everything again")
    s = sub.add_parser("search", help="show the passages search finds (no AI)")
    s.add_argument("question")
    s.add_argument("-k", type=int, default=5, help="how many passages (5)")
    a = sub.add_parser("ask", help="answer a question")
    a.add_argument("question")
    a.add_argument("--no-llm", action="store_true", help="answer with passages only, without the AI")
    sub.add_parser("stats", help="what is in the index")
    sub.add_parser("bot", help="run the Telegram bot")
    return p


def make_answerer(settings: Settings, no_llm: bool = False) -> Answerer:
    if no_llm or not settings.use_llm:
        return ExtractiveAnswerer()
    import anthropic

    return ClaudeAnswerer(
        anthropic.AsyncAnthropic(), model=settings.model, effort=settings.effort, company=settings.company
    )


def _index(kb: KnowledgeBase, settings: Settings, rebuild: bool) -> int:
    try:
        r = kb.index_folder(settings.kb_dir, max_chars=settings.chunk_chars, rebuild=rebuild)
    except FileNotFoundError:
        print(f"Папка с документами не найдена: {settings.kb_dir} (KB_DIR в .env)", file=sys.stderr)
        return 2
    print(
        f"Новых: {r.added} · изменённых: {r.updated} · удалённых: {r.removed} · "
        f"без изменений: {r.unchanged} · фрагментов в индексе: {r.chunks}"
    )
    for path, reason in r.failed:
        print(f"  не прочитан {path}: {reason}", file=sys.stderr)
    return 1 if r.failed else 0


async def _run_bot(settings: Settings, assistant: Assistant) -> None:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from rag_assistant.bot import build_dispatcher

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await build_dispatcher(settings, assistant).start_polling(bot)
    finally:
        await bot.session.close()


def run(argv: Sequence[str] | None = None, settings: Settings | None = None, answerer: Answerer | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = settings or load_settings()
    except (ValueError, RuntimeError) as exc:
        print(f"Ошибка настроек: {exc}", file=sys.stderr)
        return 2
    kb = KnowledgeBase(settings.database_path)
    try:
        if args.command == "index":
            return _index(kb, settings, args.rebuild)
        if args.command == "stats":
            s = kb.stats()
            mode = f"ИИ ({settings.model})" if settings.use_llm else "фрагменты без ИИ"
            print(
                f"Документов: {s['documents']} · фрагментов: {s['chunks']} · индексация: {s['last_indexed']} · {mode}"
            )
            return 0
        if args.command == "search":
            hits = kb.search(args.question, args.k)
            if not hits:
                print("Ничего не найдено")
            for hit in hits:
                preview = hit.text.replace("\n", " ")[:160]
                print(f"{hit.score:7.2f}  {hit.label}  ({hit.doc_path})\n         {preview}")
            return 0
        assistant = Assistant(kb, answerer or make_answerer(settings, getattr(args, "no_llm", False)), settings.top_k)
        if args.command == "ask":
            answer = asyncio.run(assistant.ask(args.question))
            print(texts.format_plain(answer, settings.contact))
            return 0
        if not settings.bot_token:
            print("BOT_TOKEN не задан в .env", file=sys.stderr)
            return 2
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(_run_bot(settings, assistant))
        return 0
    finally:
        kb.close()


def main() -> int:
    return run()
