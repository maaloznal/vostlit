"""Store / import / versioning / FTS-sync tests (master prompt §15)."""
from __future__ import annotations

import json

from vostlit_research.models import DocumentIn, SectionIn
from vostlit_research import store


def _doc(url="https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577",
         text="Гумбет и Салатавия — исторические общества Дагестана.",
         title="ИОРДАН->О ПРОИСХОЖДЕНИИ И ДЕЯНИЯХ ГЕТОВ->ЧАСТЬ 2",
         author="ИОРДАН"):
    return DocumentIn(
        canonical_url=url, page_type="document_text", title=title, author=author,
        region="Кавказ", extracted_text=text,
        sections=[SectionIn(section_type="body", text=text, sequence_number=1)],
    )


def test_upsert_creates_document_and_version(tmp_db):
    doc = _doc()
    doc_id, action = store.upsert_document(tmp_db, doc)
    assert action == "created"
    assert doc_id > 0
    row = tmp_db.conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["status"] == "parsed"
    assert row["content_hash"]
    ver = tmp_db.conn.execute("SELECT * FROM document_versions WHERE document_id=?", (doc_id,)).fetchone()
    assert ver["version_number"] == 1
    assert ver["extracted_text"] == doc.extracted_text


def test_reimport_same_text_is_idempotent(tmp_db):
    doc = _doc()
    doc_id, _ = store.upsert_document(tmp_db, doc)
    doc_id2, action = store.upsert_document(tmp_db, doc)
    assert doc_id == doc_id2
    assert action == "unchanged"
    # still exactly one version
    n = tmp_db.conn.execute("SELECT COUNT(*) c FROM document_versions WHERE document_id=?", (doc_id,)).fetchone()["c"]
    assert n == 1
    # status updated to unchanged
    row = tmp_db.conn.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["status"] == "unchanged"


def test_changed_text_creates_new_version(tmp_db):
    doc = _doc(text="версия один")
    doc_id, _ = store.upsert_document(tmp_db, doc)
    doc2 = _doc(text="версия два изменена")
    _, action = store.upsert_document(tmp_db, doc2)
    assert action == "updated"
    n = tmp_db.conn.execute("SELECT COUNT(*) c FROM document_versions WHERE document_id=?", (doc_id,)).fetchone()["c"]
    assert n == 2
    # current_version_id points at the newest
    cur = tmp_db.conn.execute("SELECT current_version_id FROM documents WHERE id=?", (doc_id,)).fetchone()
    latest = tmp_db.conn.execute("SELECT version_number FROM document_versions WHERE id=?", (cur["current_version_id"],)).fetchone()
    assert latest["version_number"] == 2


def test_dedup_by_canonical_url(tmp_db):
    # same logical URL with fragment & different case -> same document
    d1 = _doc(url="https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577")
    d2 = _doc(url="HTTPS://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577#x")
    id1, _ = store.upsert_document(tmp_db, d1)
    id2, _ = store.upsert_document(tmp_db, d2)
    assert id1 == id2
    n = tmp_db.conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    assert n == 1


def test_fts_sync_after_write(tmp_db):
    store.upsert_document(tmp_db, _doc(text="Гумбет и Салатавия горные общества Дагестана"))
    from vostlit_research.search.fts import fts_match_sections
    rows = fts_match_sections(tmp_db.conn, "гумбет")
    assert rows and rows[0]["document_id"] > 0


def test_sections_written_and_text_lower(tmp_db):
    doc = _doc(text="ГУМБЕТ Салатавия")
    doc_id, _ = store.upsert_document(tmp_db, doc)
    sec = tmp_db.conn.execute("SELECT * FROM document_sections WHERE document_id=?", (doc_id,)).fetchone()
    assert sec["text"] == "ГУМБЕТ Салатавия"
    # text_lower is Cyrillic-aware lowercased (preserves ё, keeps distinct)
    assert sec["text_lower"] == "гумбет салатавия"


def test_empty_document_is_discovered_not_parsed(tmp_db):
    doc = DocumentIn(canonical_url="https://www.vostlit.info/x.phtml?id=1", title="t")
    doc_id, action = store.upsert_document(tmp_db, doc)
    assert action == "created"
    row = tmp_db.conn.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["status"] == "discovered"
    assert tmp_db.conn.execute("SELECT COUNT(*) c FROM document_versions WHERE document_id=?", (doc_id,)).fetchone()["c"] == 0


def test_import_export_roundtrip(tmp_db, tmp_path):
    from vostlit_research.io import import_jsonl, export_jsonl
    store.upsert_document(tmp_db, _doc())
    # add a name variant + entity
    import_path = tmp_path / "in.jsonl"
    import_path.write_text(json.dumps({
        "kind": "name_variant",
        "canonical_name": "Гумбет",
        "entity_type": "society",
        "original_form": "Гумбетъ",
        "language": "ru",
        "variant_type": "historical",
        "verification_status": "candidate",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = import_jsonl(tmp_db, import_path)
    assert counts["name_variants"] == 1
    out = tmp_path / "out.jsonl"
    n = export_jsonl(tmp_db, out)
    assert n >= 2  # at least the doc + entity + variant
    # re-importing the export must not create duplicates
    counts2 = import_jsonl(tmp_db, out)
    assert counts2["errors"] == 0
    assert tmp_db.conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] == 1
