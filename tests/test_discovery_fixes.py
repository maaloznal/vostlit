"""Discovery & parser tests for v0.3.1 fixes:
  - kavkaz regional catalog → document links discovered
  - alpha index → document links discovered
  - /common/, /Repertorium/, /MGH/, /MPH/ URLs pass _is_doc_url
  - unknown page types are recorded (not silently dropped)
  - chrono.phtml table-based pages yield sections (was 0)
  - region_catalog/alpha_index are now fetchable (in fetch_page_types)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from vostlit_research.collector.parser import parse_page
from vostlit_research.collector.discover import _is_doc_url
from vostlit_research.config import Config

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------- _is_doc_url now accepts all verified document roots ----------
def test_is_doc_url_accepts_texts():
    assert _is_doc_url("https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577")


def test_is_doc_url_accepts_common():
    """QA N4: /common/ was silently dropped. Now accepted."""
    assert _is_doc_url("https://www.vostlit.info/common/itogi2020.phtml?id=12320")


def test_is_doc_url_accepts_repertorium():
    assert _is_doc_url("https://www.vostlit.info/Repertorium/doc1.htm")


def test_is_doc_url_accepts_mgh_mph():
    assert _is_doc_url("https://www.vostlit.info/MGH/x.phtml?id=1")
    assert _is_doc_url("https://www.vostlit.info/MPH/y.htm")


def test_is_doc_url_rejects_non_document():
    assert not _is_doc_url("https://www.vostlit.info/admin")
    assert not _is_doc_url("https://www.vostlit.info/")  # homepage, not a doc
    assert not _is_doc_url("https://www.vostlit.info/Texts/rus/Iordan/")  # dir, no ext


def test_is_doc_url_rejects_offsite():
    """_is_doc_url only checks path-shape (host is checked by _check_scope).
    Verify the full scope check rejects offsite hosts."""
    from vostlit_research.collector.http import HttpClient, RefusedError
    from vostlit_research.db import Database
    cfg = Config()
    cfg.db_path = Path("/tmp/_scope_test.db")
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        with pytest.raises(RefusedError):
            http._check_scope("https://evil.example.com/Texts/x.phtml")
    finally:
        http.close(); db.close()
        Path("/tmp/_scope_test.db").unlink(missing_ok=True)


# ---------- allowed_sections includes the new roots ----------
def test_allowed_sections_includes_new_roots():
    cfg = Config()
    assert "/common/" in cfg.allowed_sections
    assert "/Repertorium/" in cfg.allowed_sections
    assert "/MGH/" in cfg.allowed_sections
    assert "/MPH/" in cfg.allowed_sections
    # '/' must NOT be there (D-2)
    assert "/" not in cfg.allowed_sections


def test_fetch_page_types_includes_chrono_and_catalogs():
    cfg = Config()
    assert "chrono" in cfg.fetch_page_types
    assert "region_catalog" in cfg.fetch_page_types
    assert "alpha_index" in cfg.fetch_page_types


# ---------- kavkaz regional catalog → document links ----------
def test_kavkaz_catalog_yields_document_links():
    """The Caucasus catalog fixture must produce document links (not 0)."""
    raw = (FIXTURES / "kavkaz_catalog.fragment.html").read_bytes()
    p = parse_page("https://www.vostlit.info/Texts/Dokumenty/kavkaz.html", raw, charset="windows-1251")
    assert p.page_type == "region_catalog"
    assert len(p.links) >= 100  # fragment; full page has 300+
    assert all(lk.url.startswith("http") for lk in p.links)


# ---------- alpha index → document links ----------
def test_alpha_index_yields_document_links():
    raw = (FIXTURES / "alpha_index_G.html").read_bytes()
    p = parse_page("https://www.vostlit.info/haupt-Dateien/index-Dateien/G.phtml?id=2044",
                   raw, charset="windows-1251")
    assert p.page_type == "alpha_index"
    assert len(p.links) >= 500  # audit verified ~710
    # all links are http (no mailto leakage)
    assert all(lk.url.startswith("http") for lk in p.links)


# ---------- unknown page types are recorded, not silently dropped ----------
def test_unknown_page_type_recorded_with_warning():
    """A page that matches NO known type must be classified 'unknown' with a
    warning, so inventory can report it (not silently lost).

    To actually trigger the 'unknown' branch in classify(), we need a URL that:
      - is not the homepage
      - has no <frameset>
      - is not in /haupt-Dateien/, /Texts/Dokumenty/index.phtml, /common/itogi,
        primtext, karten, chrono, /index.htm, region_catalog pattern
      - does not end in .phtml/.htm/.html
    A URL ending in a non-document extension on an allowed path works.
    """
    # a path under /Texts/ but with a non-document extension (e.g. .xml, .css)
    html = b"""<html><head><title>weird</title></head>
    <body><div>something unusual</div></body></html>"""
    # use a .xml extension so classify() falls through to "unknown"
    p = parse_page("https://www.vostlit.info/Texts/rus/X/weird.xml", html, charset="utf-8")
    assert p.page_type == "unknown", \
        f"expected 'unknown', got {p.page_type!r} (the unknown branch must fire)"
    assert any("unclassified" in w for w in p.warnings), \
        f"expected an 'unclassified' warning, got {p.warnings}"


# ---------- chrono.phtml table-based parser ----------
def test_chrono_page_yields_sections_from_table():
    """chrono.phtml pages are table-based; the old parser gave 0 sections.
    Now the chrono parser extracts every <tr> as a body section."""
    # synthesize a chrono page (no real fixture available offline)
    html = b"""<html><head><title>X->CHRONO</title></head><body>
    <div id="main">
      <h4>AUTHOR</h4><h2>CHRONICLE</h2>
      <table>
        <tr><td>1234</td><td>Event one happened</td></tr>
        <tr><td>1235</td><td>Event two happened</td></tr>
        <tr><td>1236</td><td>Event three</td></tr>
      </table>
    </div></body></html>"""
    p = parse_page("https://www.vostlit.info/Texts/rus5/X/chrono.phtml?id=1472",
                   html, charset="utf-8")
    assert p.page_type == "chrono"
    # at least 3 body sections (one per row)
    body_secs = [s for s in p.sections if s.section_type == "body"]
    assert len(body_secs) >= 3, f"chrono gave {len(body_secs)} body sections (expected >=3)"
    # the extracted text contains the events
    assert "Event one" in (p.extracted_text or "")
    assert "Event three" in (p.extracted_text or "")


def test_chrono_empty_table_warns():
    """A chrono page with no rows must warn (not silently produce 0 sections)."""
    html = b"""<html><body><div id="main"><table></table></div></body></html>"""
    p = parse_page("https://www.vostlit.info/Texts/rus5/X/chrono.phtml?id=1", html, charset="utf-8")
    assert p.page_type == "chrono"
    assert p.warnings  # "chrono page yielded no rows" or similar


# ---------- full test of kavkaz catalog parsing produces real text ----------
def test_region_catalog_now_fetchable_and_indexable():
    """N4c: region_catalog is now in fetch_page_types, so its <td> document
    descriptions get indexed (previously discovered-only, text lost)."""
    raw = (FIXTURES / "kavkaz_catalog.fragment.html").read_bytes()
    p = parse_page("https://www.vostlit.info/Texts/Dokumenty/kavkaz.html", raw, charset="windows-1251")
    # the catalog's extracted_text should now contain document descriptions
    assert p.extracted_text  # not empty
    assert len(p.extracted_text) > 100  # has real content


# ---------- bug fix: text1.htm must NOT be treated as a catalog ----------
def test_nested_htm_doc_not_treated_as_catalog():
    """Regression: a .htm document deep in /Texts/Dokumenty/<region>/<century>/.../
    was misclassified as a region catalog by _is_catalog_or_index (which matched
    ANY .htm under /Texts/Dokumenty/). This caused discover() to harvest the
    document's links instead of storing it — silently dropping it from the corpus.
    A real region catalog is /Texts/Dokumenty/<region>.html (one segment)."""
    from vostlit_research.collector.discover import _is_catalog_or_index
    # the bug case: a nested document
    assert not _is_catalog_or_index(
        "https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XIX/1860-1880/Tri_mesjac_dag_otrjad/text1.htm"
    ), "nested text1.htm must NOT be a catalog"
    # real catalogs must still be detected
    assert _is_catalog_or_index("https://www.vostlit.info/Texts/Dokumenty/kavkaz.html")
    assert _is_catalog_or_index("https://www.vostlit.info/Texts/Dokumenty/russ.htm")
    assert _is_catalog_or_index("https://www.vostlit.info/Texts/Dokumenty/index.phtml?id=2070")
    assert _is_catalog_or_index("https://www.vostlit.info/Texts/Dokumenty/Kavkaz/VI/Dag_chron/index.htm")
