import shutil

from conftest import EXAMPLES

from rag_assistant.index import KnowledgeBase, build_query


def test_query_is_safe_and_uses_prefixes():
    assert (
        build_query('prezzi AND "parcheggio" NEAR(x) OR *') == '"prez"* OR "parchegg"* OR "near"'
    )  # FTS syntax becomes plain words, "and" is a stop word
    assert build_query("Сколько стоит парковка?") == '"сколь"* OR "стоит" OR "парков"*'
    assert build_query("a é ?? 2026") == '"2026"'
    assert build_query("как что где") == ""  # only stop words
    assert build_query("sul balcone dalla camera") == '"balco"* OR "came"*'  # Italian prepositions are dropped
    assert build_query("Password Wi-Fi e check-in?") == '"wi fi" OR "check in" OR "passwo"*'


def test_example_base_is_indexed(kb):
    stats = kb.stats()
    assert stats["documents"] == 5 and stats["chunks"] == 12  # the _bozze draft is skipped


def test_finds_the_right_passage_in_every_language(kb):
    cases = {
        "Quanto costa la tassa di soggiorno?": "Arrivo e partenza › Tassa di soggiorno",
        "Сколько стоит парковка?": "Частые вопросы (FAQ) › Парковка",
        "Can I smoke on the balcony?": "house rules",
        "Posso fumare sul balcone?": "house rules",  # "sul" must not pull in "…sul cartoncino" from Wi-Fi
        "password del wifi": "Servizi dell'hotel › Wi-Fi",
        "noleggio bici elettrica": "prezzi",
    }
    for question, label in cases.items():
        assert kb.search(question)[0].label == label, question


def test_diacritics_and_word_forms(kb):
    assert kb.search("citta musei Otzi")[0].label == "Servizi dell'hotel › Bolzano Card"  # "Ötzi" without the umlaut
    assert kb.search("завтраком")[0].label.endswith("Завтрак")  # another case ending of "завтрак"


def test_nothing_found_and_ranking_order(kb):
    assert kb.search("piscina olimpionica") == []
    hits = kb.search("check-out posticipato", limit=3)
    assert hits[0].label.endswith("Check-out")
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_incremental_update(tmp_path):
    root = tmp_path / "kb"
    shutil.copytree(EXAMPLES, root)
    base = KnowledgeBase(tmp_path / "kb.db")
    first = base.index_folder(root)
    assert (first.added, first.updated, first.unchanged) == (5, 0, 0)

    (root / "prezzi.txt").write_text("Noleggio bici elettrica: 35 € al giorno.")
    (root / "faq_ru.md").unlink()
    (root / "nuovo.md").write_text("# Piscina\n\nLa piscina è aperta dalle 9 alle 19.")
    second = base.index_folder(root)
    assert (second.added, second.updated, second.removed, second.unchanged) == (1, 1, 1, 3)
    assert "35 €" in base.search("bici elettrica")[0].text
    assert base.search("парковка") == []  # removed file is gone from the index too
    assert base.search("piscina")[0].label == "Piscina"

    third = base.index_folder(root)
    assert third.unchanged == 5 and third.added == third.updated == 0
    rebuilt = base.index_folder(root, rebuild=True)
    assert rebuilt.added == 5 and rebuilt.chunks == third.chunks
    base.close()


def test_unreadable_file_is_reported_not_fatal(tmp_path):
    (tmp_path / "ok.md").write_text("# Ok\n\nText.")
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
    base = KnowledgeBase(":memory:")
    report = base.index_folder(tmp_path)
    assert report.added == 1 and [p for p, _ in report.failed] == ["bad.pdf"]
    base.close()
