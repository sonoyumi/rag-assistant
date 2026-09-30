"""Reading documents of the knowledge base: Markdown, plain text, HTML and PDF.

Every loader returns plain text plus a title. Markdown keeps its headings: the chunker uses
them to know which section a passage belongs to ("Parking › Prices").
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

SUPPORTED = (".md", ".markdown", ".txt", ".html", ".htm", ".pdf")
MAX_FILE_BYTES = 20 * 1024 * 1024


class LoadError(ValueError):
    pass


@dataclass(frozen=True)
class Document:
    path: str  # relative to the knowledge-base folder, with "/" separators
    title: str
    text: str
    sha256: str
    markdown: bool  # headings are "#" lines


class _HTMLText(HTMLParser):
    """Collects visible text; headings become Markdown headings so sections survive."""

    SKIP = {"script", "style", "noscript", "template"}
    BLOCK = {"p", "div", "li", "br", "tr", "section", "article", "table", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._heading = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif re.fullmatch(r"h[1-6]", tag):
            self._heading = int(tag[1])
            self.parts.append("\n\n" + "#" * self._heading + " ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif re.fullmatch(r"h[1-6]", tag):
            self._heading = 0
            self.parts.append("\n\n")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        self.parts.append(data)


def _read_html(raw: str) -> tuple[str, str]:
    parser = _HTMLText()
    parser.feed(raw)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*(\n\s*)+", "\n\n", text)
    return parser.title.strip(), text.strip()


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(path)
        pages = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, ValueError, KeyError) as exc:
        raise LoadError(f"cannot read PDF: {exc}") from None
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise LoadError("PDF has no text layer (scanned image?) - OCR is not supported")
    return text


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise LoadError("unknown text encoding: save the file as UTF-8")


def _first_heading(text: str) -> str:
    match = re.search(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M)
    return match.group(1).strip() if match else ""


def load_document(path: Path, root: Path) -> Document:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise LoadError("file is larger than 20 MB")
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    title = ""
    if suffix == ".pdf":
        text, markdown = _read_pdf(path), False
    elif suffix in (".html", ".htm"):
        title, text = _read_html(_decode(raw))
        markdown = True
    else:
        text, markdown = _decode(raw), suffix in (".md", ".markdown")
    if not text.strip():
        raise LoadError("the file is empty")
    title = title or (_first_heading(text) if markdown else "") or path.stem.replace("_", " ").replace("-", " ")
    return Document(
        path=path.relative_to(root).as_posix(),
        title=title,
        text=text,
        sha256=hashlib.sha256(raw).hexdigest(),
        markdown=markdown,
    )


def find_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
        and not any(part.startswith((".", "_", "~$")) for part in p.relative_to(root).parts)
    )
