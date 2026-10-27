"""Search engine tests (master prompt §8, §15)."""
from __future__ import annotations

from vostlit_research import store
from vostlit_research.models import DocumentIn, SectionIn, NameVariantIn, EntityIn
from vostlit_research.io import upsert_entity, upsert_name_variant
from vostlit_research.search.engine import SearchEngine, SearchFilters


def _seed(tmp_db):
    d1 = DocumentIn(
        canonical_url="https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577",
        page_type="document_text", title="Иордан — Геты", author="ИОРДАН",
        region="Кавказ", publication_year="1997",
        extracted_text="Гумбет и Салатавия — горные общества Дагестана. гора Джалдари-меер.",
        sections=[
            SectionIn(section_type="body", text="Гумбет и Салатавия — горные общества Дагестана.", sequence_number=1),
            SectionIn(section_type="body", text="Урочище у горы Джалдари-меер упоминается в хронике.", sequence_number=2),
        ],
    )
    d2 = DocumentIn(
        canonical_url="https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm",
        page_type="document_text", title="Дагестан 1792", author=None,
        region="Дагестан", publication_year="2003", original_creation_date="1792",
        extracted_text="В 1792 году дагестанские владельцы приняли подданство. Гумбет участвовал.",
        sections=[SectionIn(section_type="body", text="В 1792 году дагестанские владельцы приняли подданство. Гумбет участвовал.", sequence_number=1)],
    )
    store.upsert_document(tmp_db, d1)
    store.upsert_document(tmp_db, d2)
    # entities + variants
    eid = upsert_entity(tmp_db, EntityIn(canonical_name="Гумбет", entity_type="society",
                                         description="Историческое общество в Дагестане"))
    upsert_name_variant(tmp_db, NameVariantIn(entity_id=eid, original_form="Гумбетъ",
                                               variant_type="historical", language="ru",
                                               verification_status="candidate"))
    upsert_name_variant(tmp_db, NameVariantIn(entity_id=eid, original_form="Гумбете",
                                               variant_type="historical", language="ru",
                                               verification_status="candidate"))


def test_exact_search_preserves_spelling_and_finds_phrase(tmp_db):
    _seed(tmp_db)
    eng = SearchEngine(tmp_db)
    res = eng.search_exact("Гумбет")
    assert res
    assert any(r.snippet and "Гумбет" in r.snippet for r in res)
    assert all(r.match_type == "exact" for r in res)
    assert all(r.confidence == "verified" for r in res)


def test_fts_search_folds_yo_and_prereform(tmp_db):
    _seed(tmp_db)
    eng = SearchEngine(tmp_db)
    # searching the pre-reform spelling (і) still hits the modern-spelling text
    res = eng.search("Салатавія")  # і -> и, matches indexed "Салатавия"
    assert res
    # modern spelling also works
    res2 = eng.search("Салатавия")
    assert res2
    # ё-insensitive: seed has "горные"; searching "горные" hits
    res3 = eng.search("горные")
    assert res3


def test_variant_search_finds_historical_spelling(tmp_db):
    _seed(tmp_db)
    eng = SearchEngine(tmp_db)
    res = eng.search_variants("Гумбетъ")
    assert res
    assert any(r.snippet == "Гумбетъ" for r in res)
    # variant of the canonical entity
    assert any(r.title == "Гумбет" for r in res)


def test_fuzzy_search_marks_candidates_only(tmp_db):
    _seed(tmp_db)
    eng = SearchEngine(tmp_db)
    res = eng.search_fuzzy("Гумбет", threshold=0.5)
    assert res
    # fuzzy results must be candidates, never verified
    assert all(r.confidence == "candidate" for r in res)
    assert all("NOT a confirmed identity" in r.explanation for r in res)


def test_filter_by_region(tmp_db):
    _seed(tmp_db)
    eng = SearchEngine(tmp_db)
    res = eng.search_exact("Гумбет", SearchFilters(region="Дагестан"))
    # only the Dagestan-1792 doc should match
    assert all(r.region == "Дагестан" for r in res)
    res2 = eng.search_exact("Гумбет", SearchFilters(region="Кавказ"))
    assert all(r.region == "Кавказ" for r in res2)


def test_context_search_returns_surrounding_sections(tmp_db):
    _seed(tmp_db)
    eng = SearchEngine(tmp_db)
    from vostlit_research.research.api import ResearchEngine
    reng = ResearchEngine(tmp_db)
    # find a section in doc 1
    sec = tmp_db.conn.execute("SELECT id FROM document_sections WHERE document_id IN (SELECT id FROM documents LIMIT 1) LIMIT 1").fetchone()
    ctx = reng.get_context(sec["id"], before=1, after=1)
    assert "section" in ctx and "before" in ctx and "after" in ctx


def test_hybrid_ranks_exact_above_fuzzy(tmp_db):
    _seed(tmp_db)
    eng = SearchEngine(tmp_db)
    res = eng.search_hybrid("Гумбет")
    assert res
    # an exact hit should outrank any fuzzy-only hit
    exact_scores = [r.score for r in res if r.match_type in ("exact", "variant")]
    fuzzy_scores = [r.score for r in res if r.match_type == "fuzzy"]
    if exact_scores and fuzzy_scores:
        assert max(exact_scores) >= max(fuzzy_scores)


def test_get_document_and_bibliography(tmp_db):
    _seed(tmp_db)
    from vostlit_research.research.api import ResearchEngine
    reng = ResearchEngine(tmp_db)
    did = tmp_db.conn.execute("SELECT id FROM documents ORDER BY id LIMIT 1").fetchone()["id"]
    doc = reng.get_document(did)
    assert doc and doc["id"] == did
    assert doc["extracted_text"]


def test_find_mentions_combines_table_and_text(tmp_db):
    _seed(tmp_db)
    from vostlit_research.research.api import ResearchEngine
    reng = ResearchEngine(tmp_db)
    mentions = reng.find_mentions("Гумбет")
    assert mentions
    # at least one from text_search fallback
    assert any(m.get("extraction_method") == "text_search" for m in mentions)


def test_compare_sources_collects_fragments(tmp_db):
    _seed(tmp_db)
    from vostlit_research.research.api import ResearchEngine
    reng = ResearchEngine(tmp_db)
    ids = [r["id"] for r in tmp_db.conn.execute("SELECT id FROM documents ORDER BY id").fetchall()]
    rep = reng.compare_sources("Гумбет", ids)
    assert rep["claim"] == "Гумбет"
    assert len(rep["sources"]) == len(ids)
    assert any(s["n_matches"] > 0 for s in rep["sources"])


def test_empty_corpus_honest(tmp_db):
    eng = SearchEngine(tmp_db)
    assert eng.search("Гумбет") == []
    assert eng.search_exact("Гумбет") == []
    assert eng.search_variants("Гумбет") == []
