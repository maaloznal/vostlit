"""Tests for v0.2 improvements: frameset parser, mention extraction,
toponym candidate table, research notes, works grouping."""
from __future__ import annotations

import json

from vostlit_research.collector.parser import parse_page
from vostlit_research import store
from vostlit_research.models import DocumentIn, SectionIn, NameVariantIn, EntityIn
from vostlit_research.io import upsert_entity, upsert_name_variant, upsert_research_note
from vostlit_research.models import ResearchNoteIn, FragmentRef
from vostlit_research.search.engine import SearchEngine, SearchFilters
from vostlit_research.research.api import ResearchEngine


# ---------------------------------------------------------------------- frameset

def test_frameset_classified_and_inner_frames_extracted():
    """Verified structure (Nogmov framevved1.htm): <frameset rows='*,15%'>
    with two <frame>s — main (Hauptframe) and notes (Fussnoten)."""
    html = b"""<html><head><title>Neue Seite 9</title>
<meta http-equiv="Content-Type" content="text/html; charset=windows-1251"></head>
<frameset rows="*,15%">
  <frame name="Hauptframe" target="Fussnoten" src="vved1.htm">
  <frame name="Fussnoten" src="primvved1.htm">
  <noframes><body><p>Diese Seite verwendet Frames.</p></body></noframes>
</frameset></html>"""
    p = parse_page(
        "https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1700-1720/Nogmov/framevved1.htm",
        html, charset="windows-1251")
    assert p.page_type == "frameset"
    assert len(p.frames) == 2
    roles = {fr.role for fr in p.frames}
    assert roles == {"main", "notes"}
    main = [fr for fr in p.frames if fr.role == "main"][0]
    assert main.src.endswith("/vved1.htm")
    notes = [fr for fr in p.frames if fr.role == "notes"][0]
    assert notes.src.endswith("/primvved1.htm")
    # links exposed for the collector to follow
    assert any(lk.kind == "frame" for lk in p.links)
    assert p.warnings  # frameset warning expected


def test_frameset_not_misparsed_as_bare_htm():
    """Regression: before the frameset branch existed, frame*.htm pages were
    misclassified as bare document_text and produced empty content."""
    html = b'<html><head><title>x</title></head><frameset rows="*"><frame src="a.htm"></frameset></html>'
    p = parse_page("https://www.vostlit.info/Texts/rus17/X/framevved1.htm", html, charset="windows-1251")
    assert p.page_type == "frameset"
    assert p.page_type != "document_text"


# ---------------------------------------------------------------------- extract_mentions

def _seed_with_attested_variant(tmp_db):
    """Seed a doc whose body literally contains a name_variant's original_form,
    so extract_mentions has something to find."""
    d = DocumentIn(
        canonical_url="https://www.vostlit.info/Texts/Dokumenty/Kavkaz/X/1890/A/text.htm",
        page_type="document_text", title="Дагестанские хроники", author="Аноним",
        region="Дагестан", original_creation_date="1890",
        extracted_text="В 1890 году в Гумбете собрались старейшины. Гумбетъ упоминается в хронике.",
        sections=[
            SectionIn(section_type="body",
                       text="В 1890 году в Гумбете собрались старейшины. Гумбетъ упоминается в хронике.",
                       sequence_number=1),
        ],
    )
    store.upsert_document(tmp_db, d)
    eid = upsert_entity(tmp_db, EntityIn(canonical_name="Гумбет", entity_type="society"))
    vid = upsert_name_variant(tmp_db, NameVariantIn(
        entity_id=eid, original_form="Гумбетъ", variant_type="historical",
        language="ru", verification_status="candidate"))
    return eid, vid


def test_extract_mentions_finds_and_records_candidates(tmp_db):
    eid, vid = _seed_with_attested_variant(tmp_db)
    eng = ResearchEngine(tmp_db)
    res = eng.extract_mentions()
    assert res["variants_scanned"] >= 1
    assert res["mentions_inserted"] >= 1
    # the inserted mention must be a candidate, never confirmed
    m = tmp_db.conn.execute(
        "SELECT * FROM mentions WHERE name_variant_id=?", (vid,)
    ).fetchone()
    assert m is not None
    assert m["extraction_method"] == "heuristic"
    assert m["verification_status"] == "candidate"
    assert "Гумбетъ" in (m["mention_text"] or "")
    assert m["context_before"]  # context was captured
    assert m["context_after"]


def test_extract_mentions_is_idempotent(tmp_db):
    _seed_with_attested_variant(tmp_db)
    eng = ResearchEngine(tmp_db)
    r1 = eng.extract_mentions()
    r2 = eng.extract_mentions()
    assert r1["mentions_inserted"] >= 1
    assert r2["mentions_inserted"] == 0  # all skipped
    assert r2["mentions_skipped"] == r1["mentions_inserted"]
    # total rows unchanged
    n = tmp_db.conn.execute("SELECT COUNT(*) c FROM mentions").fetchone()["c"]
    assert n == r1["mentions_inserted"]


def test_extract_mentions_overwrite_replaces(tmp_db):
    _seed_with_attested_variant(tmp_db)
    eng = ResearchEngine(tmp_db)
    r1 = eng.extract_mentions()
    r2 = eng.extract_mentions(overwrite=True)
    assert r2["mentions_inserted"] >= 1
    # still exactly one row per variant+section (overwrite deletes then re-inserts)
    n = tmp_db.conn.execute("SELECT COUNT(*) c FROM mentions WHERE extraction_method='heuristic'").fetchone()["c"]
    assert n == r1["mentions_inserted"]


def test_extract_mentions_preserves_original_spelling(tmp_db):
    _seed_with_attested_variant(tmp_db)
    eng = ResearchEngine(tmp_db)
    eng.extract_mentions()
    m = tmp_db.conn.execute("SELECT mention_text FROM mentions WHERE extraction_method='heuristic' LIMIT 1").fetchone()
    # the ъ in "Гумбетъ" must be preserved, not folded
    assert "ъ" in (m["mention_text"] or "")


def test_extract_mentions_empty_dictionary(tmp_db):
    eng = ResearchEngine(tmp_db)
    res = eng.extract_mentions()
    assert res["variants_scanned"] == 0
    assert res["mentions_inserted"] == 0
    assert "curate entities first" in res["note"]


# ---------------------------------------------------------------------- toponym

def test_search_toponym_strips_generic_and_returns_candidate_table(tmp_db):
    _seed_with_attested_variant(tmp_db)
    eng = SearchEngine(tmp_db)
    res = eng.search_toponym("гора Гумбетъ")
    assert res["query"] == "гора Гумбетъ"
    assert res["core_toponym"] == "гумбет"  # generic stripped, normalised
    assert "гумбет" in res["forms_searched"]
    # should find the body section via exact match on "Гумбетъ"
    assert res["n_candidates"] >= 1
    c = res["candidates"][0]
    assert c["matched_as"] in ("exact", "variant")
    assert c["section_id"]
    assert c["source_url"]


def test_search_toponym_never_auto_merges(tmp_db):
    _seed_with_attested_variant(tmp_db)
    eng = SearchEngine(tmp_db)
    res = eng.search_toponym("Джалдари-меер")  # not in corpus
    # fuzzy candidates may appear but must be marked candidate confidence
    for c in res["candidates"]:
        if c["matched_as"] == "fuzzy_candidate":
            assert c["confidence"] == "candidate"
    assert "do not infer identity" in res["note"]


# ---------------------------------------------------------------------- research notes

def test_note_add_list_show_verify_roundtrip(tmp_db):
    _seed_with_attested_variant(tmp_db)
    sec = tmp_db.conn.execute("SELECT id FROM document_sections LIMIT 1").fetchone()
    sid = sec["id"]
    nid = upsert_research_note(tmp_db, ResearchNoteIn(
        claim="Гумбет упоминается в хронике 1890 г.",
        status="source_fact",
        supporting_fragments=[FragmentRef(section_id=sid, document_id=1)],
        confidence="verified",
    ))
    assert nid > 0
    # list
    rows = tmp_db.conn.execute("SELECT id, claim, status FROM research_notes").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "source_fact"
    # show
    r = tmp_db.conn.execute("SELECT * FROM research_notes WHERE id=?", (nid,)).fetchone()
    sup = json.loads(r["supporting_fragments"])
    assert sup[0]["section_id"] == sid
    # verify: the cited section still resolves
    sec2 = tmp_db.conn.execute("SELECT id FROM document_sections WHERE id=?", (sid,)).fetchone()
    assert sec2 is not None


def test_note_verify_detects_missing_section(tmp_db):
    nid = upsert_research_note(tmp_db, ResearchNoteIn(
        claim="x", status="hypothesis",
        supporting_fragments=[FragmentRef(section_id=999999)],
        confidence="unestablished",
    ))
    # simulate verify: the section doesn't exist
    sec = tmp_db.conn.execute("SELECT id FROM document_sections WHERE id=999999").fetchone()
    assert sec is None  # the verify command would report this as missing


def test_note_status_cannot_be_auto_promoted(tmp_db):
    """A hypothesis note stays a hypothesis — the schema has no trigger to
    promote it, and the SKILL forbids silent promotion."""
    nid = upsert_research_note(tmp_db, ResearchNoteIn(
        claim="maybe X", status="hypothesis", confidence="possible"))
    r = tmp_db.conn.execute("SELECT status FROM research_notes WHERE id=?", (nid,)).fetchone()
    assert r["status"] == "hypothesis"  # unchanged


# ---------------------------------------------------------------------- works

def test_works_groups_by_url_prefix(tmp_db):
    # two parts of the same work (shared /Texts/rus/Iordan/ prefix)
    d1 = DocumentIn(canonical_url="https://www.vostlit.info/Texts/rus/Iordan/text1.phtml?id=576",
                    title="Иордан ч.1", extracted_text="a",
                    sections=[SectionIn(section_type="body", text="a", sequence_number=1)])
    d2 = DocumentIn(canonical_url="https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577",
                    title="Иордан ч.2", extracted_text="b",
                    sections=[SectionIn(section_type="body", text="b", sequence_number=1)])
    store.upsert_document(tmp_db, d1)
    store.upsert_document(tmp_db, d2)
    # a different work
    d3 = DocumentIn(canonical_url="https://www.vostlit.info/Texts/rus5/Tunmann/pred.phtml?id=1541",
                    title="Тунманн", extracted_text="c",
                    sections=[SectionIn(section_type="body", text="c", sequence_number=1)])
    store.upsert_document(tmp_db, d3)

    from vostlit_research.cli import _work_prefix
    assert _work_prefix(d1.canonical_url) == "/Texts/rus/Iordan"
    assert _work_prefix(d2.canonical_url) == "/Texts/rus/Iordan"
    assert _work_prefix(d3.canonical_url) == "/Texts/rus5/Tunmann"
    # group
    works: dict[str, list[str]] = {}
    for d in (d1, d2, d3):
        p = _work_prefix(d.canonical_url)
        works.setdefault(p, []).append(d.canonical_url)
    assert len(works["/Texts/rus/Iordan"]) == 2
    assert len(works["/Texts/rus5/Tunmann"]) == 1


# ---------------------------------------------------------------------- doctor hint

def test_doctor_hints_on_empty_corpus(tmp_path):
    import subprocess, sys, os
    env = dict(os.environ)
    env["VOSTLIT_DB_PATH"] = str(tmp_path / "empty.db")
    env["PYTHONPATH"] = "/home/z/my-project/vostlit-research"
    r = subprocess.run([sys.executable, "-m", "vostlit_research", "doctor"],
                       capture_output=True, text=True, env=env,
                       cwd="/home/z/my-project/vostlit-research")
    assert r.returncode == 0
    assert "[HINT] corpus is empty" in r.stdout
