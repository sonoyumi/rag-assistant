"""The search index: SQLite with FTS5 full-text search and BM25 ranking.

No embeddings service and no vector database: for a company knowledge base of hundreds of
documents, BM25 with prefix matching finds the right passages, costs nothing and works
offline. The index is incremental: unchanged files (same SHA-256) are skipped.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rag_assistant.chunker import chunk_document
from rag_assistant.loaders import LoadError, find_files, load_document

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    indexed_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY,
    doc_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    heading   TEXT NOT NULL,
    text      TEXT NOT NULL
);
-- rowid of the FTS row = chunks.id. remove_diacritics: "citta" finds "città", "caffe" finds "caffè".
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    heading, text, tokenize = 'unicode61 remove_diacritics 2'
);
"""

# Words that match almost every passage and only add noise to the ranking.
STOPWORDS = frozenset(
    """
    the and for are you your can how what when where which with from that this have has does
    che per con una uno del della delle dei degli nel nella come quando dove cosa sono posso puo può
    sul sulla sullo sui sugli alla allo alle agli dal dalla dallo dai dagli nei negli nelle tra fra gli
    как что где когда это для или при про без мне можно есть ваш ваша наш the
    які який яка коли що для або мені можна
    """.split()
)
HEADING_WEIGHT, TEXT_WEIGHT = 2.0, 1.0  # a word in the section title counts double


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    doc_path: str
    doc_title: str
    heading: str
    text: str
    score: float  # higher = more relevant

    @property
    def label(self) -> str:
        """ "Title › Section" without repeating the title when it is also the top heading."""
        if not self.heading:
            return self.doc_title
        if self.heading == self.doc_title or self.heading.startswith(self.doc_title + " › "):
            return self.heading
        return f"{self.doc_title} › {self.heading}"


@dataclass
class IndexReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    chunks: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def build_query(text: str) -> str:
    """User text -> safe FTS5 query. Every term is quoted, so FTS5 syntax in the question
    (AND, NEAR, quotes, *) is treated as plain words. Long words also match by prefix:
    "prezzi" finds "prezzo", "парковки" finds "парковка" - a cheap multilingual stemmer.
    Hyphenated words ("Wi-Fi", "check-in") become phrases, so their short parts still count."""
    text = text.lower()
    terms: list[str] = []
    for compound in dict.fromkeys(re.findall(r"\w+(?:-\w+)+", text)):
        terms.append('"' + " ".join(compound.split("-")) + '"')
    text = re.sub(r"\w+(?:-\w+)+", " ", text)
    for word in dict.fromkeys(re.findall(r"\w+", text)):
        if len(word) < 3 or word in STOPWORDS:
            continue
        if len(word) >= 6 and not word.isdigit():
            terms.append(f'"{word[:-2]}"*')
        else:
            terms.append(f'"{word}"')
    return " OR ".join(terms[:30])


class KnowledgeBase:
    def __init__(self, db_path: Path | str) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by the bot's threads; the lock keeps statements from interleaving.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def _delete_document(self, doc_id: int) -> None:
        self._conn.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE doc_id = ?)", (doc_id,))
        self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))  # chunks: ON DELETE CASCADE

    def index_folder(self, root: Path, *, max_chars: int = 1200, rebuild: bool = False) -> IndexReport:
        report = IndexReport()
        files = find_files(root)
        with self._lock, self._conn:  # one transaction: a failed run leaves the old index intact
            if rebuild:
                self._conn.execute("DELETE FROM chunks_fts")
                self._conn.execute("DELETE FROM documents")
            known = {
                r["path"]: (r["id"], r["sha256"]) for r in self._conn.execute("SELECT id, path, sha256 FROM documents")
            }
            seen: set[str] = set()
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            for path in files:
                rel = path.relative_to(root).as_posix()
                seen.add(rel)
                try:
                    doc = load_document(path, root)
                except (LoadError, OSError) as exc:
                    report.failed.append((rel, str(exc)))
                    continue
                old = known.get(rel)
                if old and old[1] == doc.sha256:
                    report.unchanged += 1
                    continue
                if old:
                    self._delete_document(old[0])
                    report.updated += 1
                else:
                    report.added += 1
                cursor = self._conn.execute(
                    "INSERT INTO documents (path, title, sha256, indexed_at) VALUES (?, ?, ?, ?)",
                    (doc.path, doc.title, doc.sha256, now),
                )
                doc_id = cursor.lastrowid
                for chunk in chunk_document(doc.text, doc.markdown, max_chars):
                    cur = self._conn.execute(
                        "INSERT INTO chunks (doc_id, position, heading, text) VALUES (?, ?, ?, ?)",
                        (doc_id, chunk.position, chunk.heading, chunk.text),
                    )
                    self._conn.execute(
                        "INSERT INTO chunks_fts (rowid, heading, text) VALUES (?, ?, ?)",
                        (cur.lastrowid, chunk.heading, chunk.text),
                    )
            for rel, (doc_id, _) in known.items():
                if rel not in seen:
                    self._delete_document(doc_id)
                    report.removed += 1
            report.chunks = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return report

    def search(self, question: str, limit: int = 5) -> list[Hit]:
        query = build_query(question)
        if not query:
            return []
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT c.id, d.path, d.title, c.heading, c.text,
                       -bm25(chunks_fts, {HEADING_WEIGHT}, {TEXT_WEIGHT}) AS score
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.rowid
                JOIN documents d ON d.id = c.doc_id
                WHERE chunks_fts MATCH ?
                ORDER BY score DESC, c.id
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [Hit(r[0], r[1], r[2], r[3], r[4], round(r[5], 4)) for r in rows]

    def stats(self) -> dict[str, int | str]:
        with self._lock:
            docs = self._conn.execute("SELECT COUNT(*), MAX(indexed_at) FROM documents").fetchone()
            chunks = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"documents": docs[0], "chunks": chunks, "last_indexed": docs[1] or "—"}
