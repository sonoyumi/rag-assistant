"""The service used by both the bot and the CLI: search the index, then answer."""

from __future__ import annotations

import asyncio
import logging

from rag_assistant.answer import Answer, Answerer, AnswerError, ExtractiveAnswerer
from rag_assistant.index import KnowledgeBase

logger = logging.getLogger(__name__)


class Assistant:
    def __init__(self, kb: KnowledgeBase, answerer: Answerer, top_k: int = 5) -> None:
        self.kb = kb
        self.answerer = answerer
        self.top_k = top_k
        self._extractive = ExtractiveAnswerer()

    async def ask(self, question: str) -> Answer:
        # SQLite is synchronous: run the search in a thread so the bot keeps answering others.
        hits = await asyncio.to_thread(self.kb.search, question, self.top_k)
        try:
            return await self.answerer.answer(question, hits)
        except AnswerError as exc:
            # The AI is unavailable: the customer still gets the relevant passages.
            logger.warning("AI answer failed (%s), falling back to passages", exc)
            answer = await self._extractive.answer(question, hits)
            answer.note = str(exc)
            return answer
