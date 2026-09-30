import pytest
from pdfgen import make_pdf

from rag_assistant import loaders
from rag_assistant.chunker import chunk_document
from rag_assistant.loaders import LoadError, find_files, load_document


def test_find_files_skips_drafts_hidden_and_unsupported(tmp_path):
    for name in ("a.md", "b.txt", "c.html", "d.pdf", "e.docx", ".hidden.md", "_drafts/x.md", "sub/f.md", "~$tmp.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    assert [p.relative_to(tmp_path).as_posix() for p in find_files(tmp_path)] == [
        "a.md",
        "b.txt",
        "c.html",
        "d.pdf",
        "sub/f.md",
    ]
    with pytest.raises(FileNotFoundError):
        find_files(tmp_path / "missing")


def test_markdown_title_from_first_heading(tmp_path):
    (tmp_path / "faq.md").write_text("# Domande frequenti\n\n## Wi-Fi\nGratis.")
    doc = load_document(tmp_path / "faq.md", tmp_path)
    assert doc.title == "Domande frequenti" and doc.markdown and doc.path == "faq.md" and len(doc.sha256) == 64


def test_html_keeps_headings_and_drops_scripts(tmp_path):
    html = (
        "<html><head><title>Servizi</title><script>alert(1)</script></head>"
        "<body><h2>Wi-Fi</h2><p>Gratis &amp; veloce</p></body></html>"
    )
    (tmp_path / "s.html").write_text(html)
    doc = load_document(tmp_path / "s.html", tmp_path)
    assert doc.title == "Servizi" and "## Wi-Fi" in doc.text and "Gratis & veloce" in doc.text
    assert "alert" not in doc.text


def test_text_in_windows_encoding_and_title_from_file_name(tmp_path):
    (tmp_path / "listino_prezzi.txt").write_bytes("Caffè: 1,20 €".encode("cp1252"))
    doc = load_document(tmp_path / "listino_prezzi.txt", tmp_path)
    assert doc.text == "Caffè: 1,20 €" and doc.title == "listino prezzi" and not doc.markdown


def test_pdf_text_and_errors(tmp_path):
    (tmp_path / "rules.pdf").write_bytes(make_pdf(["Quiet hours from 22:00"]))
    assert "Quiet hours from 22:00" in load_document(tmp_path / "rules.pdf", tmp_path).text
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(LoadError):
        load_document(tmp_path / "broken.pdf", tmp_path)
    (tmp_path / "empty.md").write_text("   ")
    with pytest.raises(LoadError, match="empty"):
        load_document(tmp_path / "empty.md", tmp_path)


def test_file_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(loaders, "MAX_FILE_BYTES", 5)
    (tmp_path / "big.md").write_text("0123456789")
    with pytest.raises(LoadError, match="20 MB"):
        load_document(tmp_path / "big.md", tmp_path)


def test_chunks_carry_the_section_path():
    text = "# Hotel\n\nIntro.\n\n## Parcheggio\n\n### Prezzi\n\n12 € al giorno.\n\n## Colazione\n\nDalle 7."
    chunks = chunk_document(text, markdown=True)
    assert [(c.heading, c.text) for c in chunks] == [
        ("Hotel", "Intro."),
        ("Hotel › Parcheggio › Prezzi", "12 € al giorno."),
        ("Hotel › Colazione", "Dalle 7."),
    ]


def test_long_sections_are_split_with_overlap():
    paragraphs = [f"Paragraph {i} " + "word " * 40 for i in range(6)]
    chunks = chunk_document("\n\n".join(paragraphs), markdown=False, max_chars=500)
    assert len(chunks) > 1 and all(len(c.text) <= 500 for c in chunks)
    assert [c.position for c in chunks] == list(range(len(chunks)))
    # the last paragraph of a chunk starts the next one, so a thought crossing the border is not lost
    assert chunks[1].text.startswith(chunks[0].text.split("\n\n")[-1])


def test_huge_paragraph_is_cut_by_sentences_then_characters():
    sentences = ". ".join(f"Sentence number {i}" for i in range(60)) + "."
    chunks = chunk_document(sentences, markdown=False, max_chars=300)
    assert all(len(c.text) <= 300 for c in chunks) and chunks[0].text.startswith("Sentence number 0")
    blob = chunk_document("x" * 1000, markdown=False, max_chars=300)
    assert [len(c.text) for c in blob] == [300, 300, 300, 100]
