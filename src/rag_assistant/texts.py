"""Texts the bot shows and the formatting of answers for Telegram (HTML) and the terminal."""

from __future__ import annotations

from html import escape

from rag_assistant.answer import Answer

TELEGRAM_LIMIT = 4096

START = (
    "👋 Здравствуйте! Я отвечаю на вопросы по документам {company}.\n\n"
    "Просто напишите вопрос, например: <i>«Во сколько заезд?»</i> или <i>«Сколько стоит парковка?»</i>\n"
    "Под ответом будут источники — откуда взята информация."
)
HELP = "<b>Как пользоваться</b>\nНапишите вопрос обычным сообщением. /start — приветствие, /help — эта подсказка."
ADMIN_HELP = "\n\n<b>Для администратора</b>\n/reindex — перечитать документы\n/stats — что в базе знаний"
NOT_ALLOWED = "Этот бот работает только для сотрудников. Обратитесь к администратору."
TOO_LONG = "Вопрос слишком длинный (больше {limit} символов). Сформулируйте короче, пожалуйста."
RATE_LIMITED = "Слишком много вопросов подряд. Попробуйте через {minutes} мин."
ADMIN_ONLY = "Эта команда доступна только администратору."
ONLY_TEXT = "Я понимаю только текстовые вопросы 🙂"
NOT_FOUND = "😔 В документах нет ответа на этот вопрос."
DEGRADED = "⚠️ ИИ сейчас недоступен ({reason}), поэтому показываю подходящие фрагменты документов:"
MODE_LABELS = {
    "llm": "ИИ по документам",
    "extractive": "фрагменты документов",
    "not_found": "нет ответа",
    "refusal": "отказ",
}


def not_found_text(contact: str) -> str:
    return NOT_FOUND + (f"\n{contact}" if contact else "")


def format_html(answer: Answer, contact: str = "") -> str:
    if answer.mode == "not_found":
        return escape(not_found_text(contact))
    head = escape(DEGRADED.format(reason=answer.note)) + "\n\n" if answer.note else ""
    body = escape(answer.text)
    if answer.sources:
        lines = [f"[{s.number}] {escape(s.label)} <i>({escape(s.path)})</i>" for s in answer.sources]
        body += "\n\n<b>Источники:</b>\n" + "\n".join(lines)
    return head + body


def format_plain(answer: Answer, contact: str = "") -> str:
    if answer.mode == "not_found":
        return not_found_text(contact)
    head = DEGRADED.format(reason=answer.note) + "\n\n" if answer.note else ""
    body = answer.text
    if answer.sources:
        body += "\n\nИсточники:\n" + "\n".join(f"[{s.number}] {s.label} ({s.path})" for s in answer.sources)
    return head + body


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Telegram refuses messages over 4096 characters: split on paragraph borders."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for paragraph in text.split("\n\n"):
        while len(paragraph) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > limit:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts
