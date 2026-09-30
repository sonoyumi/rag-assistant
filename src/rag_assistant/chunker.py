"""Splitting documents into passages ("chunks") that search can find and Claude can cite.

- Markdown is split by headings first: every chunk knows its section path ("Parking › Prices").
- Long sections are split by paragraphs into chunks of about `max_chars`; one paragraph
  of overlap keeps a sentence that continues across the border findable from both sides.
- A single huge paragraph is cut by sentences, and as a last resort by characters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class Chunk:
    heading: str  # "Section › Subsection" or ""
    text: str
    position: int  # order inside the document


def _sections(text: str, markdown: bool) -> list[tuple[str, str]]:
    if not markdown:
        return [("", text)]
    sections: list[tuple[str, str]] = []
    path: list[str] = []
    current: list[str] = []
    heading = ""
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            if "".join(current).strip():
                sections.append((heading, "\n".join(current)))
            level = len(match.group(1))
            path = path[: level - 1] + [match.group(2).strip()]
            heading = " › ".join(path)
            current = []
        else:
            current.append(line)
    if "".join(current).strip():
        sections.append((heading, "\n".join(current)))
    return sections


def _pieces(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    out, buf = [], ""
    for sentence in SENTENCE_END.split(paragraph):
        while len(sentence) > max_chars:  # no sentence breaks at all: hard cut
            out.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if buf and len(buf) + 1 + len(sentence) > max_chars:
            out.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        out.append(buf)
    return out


def chunk_document(text: str, markdown: bool, max_chars: int = 1200) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, body in _sections(text, markdown):
        paragraphs = []
        for block in re.split(r"\n\s*\n", body):
            block = re.sub(r"[ \t]+", " ", block).strip()
            if block:
                paragraphs.extend(_pieces(block, max_chars))
        buf: list[str] = []
        for paragraph in paragraphs:
            if buf and len("\n\n".join(buf)) + 2 + len(paragraph) > max_chars:
                chunks.append(Chunk(heading, "\n\n".join(buf), len(chunks)))
                buf = [buf[-1]] if len(buf[-1]) + len(paragraph) + 2 <= max_chars else []
            buf.append(paragraph)
        if buf:
            chunks.append(Chunk(heading, "\n\n".join(buf), len(chunks)))
    return chunks
