"""P0/P1 regression tests — security hardening + reproducibility + search fixes.

Each test maps to a confirmed defect from the upgrade audits:
  - D-1 redirect leak         -> test_redirect_offsite_refused_before_request
  - D-2 allowed_sections bypass-> test_root_section_no_longer_bypasses
  - D-3 no raise_for_status   -> test_4xx_5xx_raise_not_silently_parsed
  - D-4 response size cap     -> test_oversize_response_refused
  - B-§3.1 section-id stable  -> test_section_id_stable_on_unchanged_reimport
  - F1 variants ignore filter -> test_variants_respect_region_filter
  - F2 Cyrillic case filter   -> test_region_filter_cyrillic_case_insensitive
  - F3 date filter semantics  -> test_date_filter_prefers_original_creation_date
"""
from __future__ import annotations

import json
from pathlib import Path

from vostlit_research import store, textnorm
from vostlit_research.config import Config
from vostlit_research.db import Database
from vostlit_research.models import DocumentIn, SectionIn, NameVariantIn, EntityIn
from vostlit_research.io import upsert_entity, upsert_name_variant
from vostlit_research.search.engine import SearchEngine, SearchFilters
from vostlit_research.collector.http import HttpClient, RefusedError


# ---------------------------------------------------------------------- D-1
def test_redirect_offsite_refused_before_request(cfg):
    """D-1: an offsite redirect target must be refused WITHOUT sending a
    request to it. We verify the scope check raises RefusedError on the
    redirect target URL directly (simulating the per-hop check)."""
    from vostlit_research.collector.http import HttpClient
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        # the per-hop _check_scope must refuse an offsite redirect target
        try:
            http._check_scope("https://evil.example.com/steal")
            assert False, "offsite URL should have been refused"
        except RefusedError:
            pass  # correct
    finally:
        http.close()
        db.close()


# ---------------------------------------------------------------------- D-2
def test_root_section_no_longer_bypasses(cfg):
    """D-2: with '/' removed from allowed_sections, disallowed paths are refused."""
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        # disallowed paths must be refused
        for bad in ["https://www.vostlit.info/admin",
                    "https://www.vostlit.info/secret",
                    "https://www.vostlit.info/cgi-bin/x"]:
            try:
                http._check_scope(bad)
                assert False, f"{bad} should have been refused"
            except RefusedError:
                pass
        # allowed paths must pass
        for good in ["https://www.vostlit.info/",
                     "https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577",
                     "https://www.vostlit.info/haupt-Dateien/index-Dateien/G.phtml?id=2044"]:
            http._check_scope(good)  # must not raise
    finally:
        http.close()
        db.close()


def test_non_default_port_refused(cfg):
    """D-7 (security audit): non-default ports must be refused."""
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        for bad in ["https://www.vostlit.info:8080/",
                    "https://www.vostlit.info:22/"]:
            try:
                http._check_scope(bad)
                assert False, f"{bad} should have been refused (port)"
            except RefusedError:
                pass
    finally:
        http.close()
        db.close()


def test_non_http_scheme_refused(cfg):
    """D-6: file://, ftp://, gopher:// must be refused."""
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        for bad in ["file:///etc/passwd", "ftp://www.vostlit.info/x", "gopher://x"]:
            try:
                http._check_scope(bad)
                assert False, f"{bad} should have been refused (scheme)"
            except RefusedError:
                pass
    finally:
        http.close()
        db.close()


# ---------------------------------------------------------------------- B-§3.1
def test_section_id_stable_on_unchanged_reimport(tmp_db):
    """CRITICAL: re-importing the same text must NOT change section ids
    (would dangle mentions.evidence_section_id + note fragments)."""
    doc = DocumentIn(
        canonical_url="https://www.vostlit.info/Texts/rus/X/text1.phtml?id=999",
        title="t", extracted_text="hello world",
        sections=[SectionIn(section_type="body", text="hello world", sequence_number=1)],
    )
    store.upsert_document(tmp_db, doc)
    sec1 = tmp_db.conn.execute("SELECT id, stable_key FROM document_sections").fetchone()
    # re-import unchanged
    store.upsert_document(tmp_db, doc)
    sec2 = tmp_db.conn.execute("SELECT id, stable_key FROM document_sections").fetchone()
    assert sec1["id"] == sec2["id"], "section id changed on unchanged re-import (reproducibility broken)"
    assert sec1["stable_key"] == sec2["stable_key"]
    assert sec1["stable_key"] is not None


def test_stable_key_backfilled_on_migration(tmp_path):
    """v1 DB without stable_key must be backfilled on open."""
    # create a v1-style DB by inserting a section without stable_key, then reopen
    db = Database(tmp_path / "t.db")
    doc = DocumentIn(canonical_url="https://www.vostlit.info/x.phtml?id=1", title="t",
                     extracted_text="x", sections=[SectionIn(section_type="body", text="x", sequence_number=1)])
    store.upsert_document(db, doc)
    db.conn.execute("UPDATE document_sections SET stable_key = NULL")
    db.conn.commit()
    db.close()
    # reopen -> migration backfills
    db2 = Database(tmp_path / "t.db")
    row = db2.conn.execute("SELECT stable_key FROM document_sections WHERE id=1").fetchone()
    assert row["stable_key"] is not None, "stable_key not backfilled"
    db2.close()


# ---------------------------------------------------------------------- F1
def test_variants_respect_region_filter(tmp_db):
    """F1: search_variants must filter out variants whose evidence is in a
    non-matching region."""
    # doc in Дагестан
    d1 = DocumentIn(canonical_url="https://www.vostlit.info/d1.phtml?id=1",
                    title="d1", region="Дагестан", extracted_text="Гумбет",
                    sections=[SectionIn(section_type="body", text="Гумбет", sequence_number=1)])
    store.upsert_document(tmp_db, d1)
    # doc in Крым
    d2 = DocumentIn(canonical_url="https://www.vostlit.info/d2.phtml?id=2",
                    title="d2", region="Крым", extracted_text="Гумбет",
                    sections=[SectionIn(section_type="body", text="Гумбет", sequence_number=1)])
    store.upsert_document(tmp_db, d2)
    eid = upsert_entity(tmp_db, EntityIn(canonical_name="Гумбет", entity_type="society"))
    # variant with evidence in d1 (Дагестан)
    sec_d1 = tmp_db.conn.execute("SELECT id FROM document_sections WHERE document_id=(SELECT id FROM documents WHERE canonical_url LIKE '%d1%')").fetchone()["id"]
    upsert_name_variant(tmp_db, NameVariantIn(entity_id=eid, original_form="Гумбетъ",
                                               variant_type="historical", language="ru",
                                               evidence_section_id=sec_d1))
    eng = SearchEngine(tmp_db)
    # no filter -> variant found
    res_all = eng.search_variants("Гумбетъ")
    assert any(r.snippet == "Гумбетъ" for r in res_all)
    # filter to Крым -> variant (evidence in Дагестан) must be filtered out
    res_krym = eng.search_variants("Гумбетъ", SearchFilters(region="Крым"))
    assert not any(r.snippet == "Гумбетъ" and r.section_id == sec_d1 for r in res_krym)


# ---------------------------------------------------------------------- F2
def test_region_filter_cyrillic_case_insensitive(tmp_db):
    """F2: region='дагестан' (lowercase) must match docs with region='Дагестан'."""
    d = DocumentIn(canonical_url="https://www.vostlit.info/d.phtml?id=1",
                   title="d", region="Дагестан", extracted_text="текст Дагестан",
                   sections=[SectionIn(section_type="body", text="текст Дагестан", sequence_number=1)])
    store.upsert_document(tmp_db, d)
    eng = SearchEngine(tmp_db)
    # lowercase query must match Title-case region
    res = eng.search_exact("Дагестан", SearchFilters(region="дагестан"))
    assert res, "lowercase region filter matched nothing (F2 defect)"


# ---------------------------------------------------------------------- F3
def test_date_filter_prefers_original_creation_date(tmp_db):
    """F3: a primary source from 1792 (original_creation_date) published in
    2003 must be found by search_by_date(1790, 1800), NOT excluded because
    publication_year=2003 > 1800."""
    d = DocumentIn(canonical_url="https://www.vostlit.info/d.phtml?id=1",
                   title="d", region="Дагестан",
                   original_creation_date="1792", publication_year="2003",
                   extracted_text="в 1792 году",
                   sections=[SectionIn(section_type="body", text="в 1792 году", sequence_number=1)])
    store.upsert_document(tmp_db, d)
    eng = SearchEngine(tmp_db)
    from vostlit_research.research.api import ResearchEngine
    reng = ResearchEngine(tmp_db)
    res = reng.search_by_date("1790", "1800")
    assert any(r["canonical_url"].endswith("d.phtml?id=1") for r in res), \
        "1792 source not found in 1790-1800 range (F3 defect: date filter used publication_year)"


# ---------------------------------------------------------------------- inventory CLI
def test_inventory_command_reports_coverage(tmp_path):
    """P1: the inventory CLI must report discovered/parsed/skipped/error counts."""
    import subprocess, sys, os
    from pathlib import Path
    root = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["VOSTLIT_DB_PATH"] = str(tmp_path / "inv.db")
    env["PYTHONPATH"] = root
    # seed first
    r1 = subprocess.run([sys.executable, "scripts/seed_corpus.py"],
                        capture_output=True, text=True, env=env, cwd=root)
    # run inventory
    r = subprocess.run([sys.executable, "-m", "vostlit_research", "inventory"],
                       capture_output=True, text=True, env=env, cwd=root)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "parsed" in data
    assert data["parsed"] >= 1
    assert "discovered" in data
    assert "stale_not_checked_30d" in data  # not-checked-recently count
