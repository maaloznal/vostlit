"""Parser tests — every assertion is backed by a verified fixture (see
tests/fixtures/fixtures_manifest.json and docs/SITE_AUDIT.md)."""
from __future__ import annotations

from vostlit_research.collector.parser import parse_page


def _parse(filename, url, fixture_bytes):
    return parse_page(url, fixture_bytes(filename), charset="windows-1251")


def test_homepage_classifies_and_extracts_featured_links(fixture_bytes, fixture_url):
    p = _parse("home.html", fixture_url["home.html"], fixture_bytes)
    assert p.page_type == "home"
    assert "Восточная Литература" in (p.title or "")
    assert any("/Texts/" in lk.url for lk in p.links)


def test_alpha_index_extracts_part_links(fixture_bytes, fixture_url):
    p = _parse("alpha_index_G.html", fixture_url["alpha_index_G.html"], fixture_bytes)
    assert p.page_type == "alpha_index"
    assert "АВТОРЫ" in (p.title or "")
    # audit verified ~710 /Texts/ links on this page
    assert len(p.links) > 500
    assert all(lk.url.startswith("http") for lk in p.links)


def test_documents_hub_lists_regions(fixture_bytes, fixture_url):
    p = _parse("dokumenty_hub.html", fixture_url["dokumenty_hub.html"], fixture_bytes)
    assert p.page_type == "documents_hub"
    assert len(p.links) >= 40  # audit: 45 regions


def test_phtml_doc_extracts_breadcrumb_author_work_citation(fixture_bytes, fixture_url):
    p = _parse("document_text_iordan_text2.html",
               fixture_url["document_text_iordan_text2.html"], fixture_bytes)
    assert p.page_type == "document_text"
    assert p.author == "ИОРДАН"
    assert "О ПРОИСХОЖДЕНИИ И ДЕЯНИЯХ ГЕТОВ" in (p.work_title or "")
    assert p.publication_year == "1997"
    assert p.citation and "Текст воспроизведен по изданию" in p.citation
    # the citation #dann must NOT leak into body
    assert "© текст" not in (p.extracted_text or "")
    # page-break markers extracted as their own sections
    assert sum(1 for s in p.sections if s.section_type == "page_break") == 33
    # links to the range-batched notes pages
    assert any("primtext" in lk.url for lk in p.links)


def test_phtml_doc_inline_notes_section(fixture_bytes, fixture_url):
    p = _parse("document_text_tunmann_pred.html",
               fixture_url["document_text_tunmann_pred.html"], fixture_bytes)
    assert p.author == "ИОГАНН ТУНМАНН"
    notes = [s for s in p.sections if s.section_type == "note"]
    assert len(notes) >= 3  # audit: inline Комментарии with numbered notes
    assert p.publication_year == "1991"


def test_phtml_doc_esai_caucasus(fixture_bytes, fixture_url):
    p = _parse("document_text_esai_pred2.html",
               fixture_url["document_text_esai_pred2.html"], fixture_bytes)
    assert p.author == "ЕСАИ ХАСАН-ДЖАЛАЛЯН"
    assert "АЛБАНСКОЙ" in (p.work_title or "")
    assert p.publication_year == "1989"


def test_image_gallery_extracts_image_refs(fixture_bytes, fixture_url):
    p = _parse("document_text_sirvan_derbend_karten.html",
               fixture_url["document_text_sirvan_derbend_karten.html"], fixture_bytes)
    assert p.page_type == "image_gallery"
    assert len(p.images) == 5
    assert all(im.url.endswith(".JPG") for im in p.images)


def test_bare_htm_doc_dagestan_1792(fixture_bytes, fixture_url):
    p = _parse("document_text_dagestan_1792.html",
               fixture_url["document_text_dagestan_1792.html"], fixture_bytes)
    assert p.page_type == "document_text"
    assert p.title and "ПОДДАННЫХ" in p.title
    # publication year = the journal year (2003), NOT the document date 1792
    assert p.publication_year == "2003"
    # the document date is captured separately
    assert p.original_creation_date == "1792"
    assert p.citation and "Текст воспроизведен по изданию" in p.citation
    notes = [s for s in p.sections if s.section_type == "note"]
    assert len(notes) >= 5  # audit: numbered Коммент. block


def test_collection_index_dag_chron(fixture_bytes, fixture_url):
    p = _parse("document_text_dag_chron_index.html",
               fixture_url["document_text_dag_chron_index.html"], fixture_bytes)
    assert p.page_type == "collection_index"
    assert "ДАГЕСТАНСКИЕ ИСТОРИЧЕСКИЕ СОЧИНЕНИЯ" == p.title
    # 13 sub-work headings + part links
    assert len([s for s in p.sections if s.section_type == "heading"]) >= 10
    assert len(p.links) >= 20


def test_notes_page_extracts_numbered_notes(fixture_bytes, fixture_url):
    p = _parse("notes_page_iordan_primtext6.html",
               fixture_url["notes_page_iordan_primtext6.html"], fixture_bytes)
    assert p.page_type == "notes_page"
    notes = [s for s in p.sections if s.section_type == "note"]
    assert len(notes) >= 50
    # note anchors are the note numbers (421, 422, ...)
    anchors = [s.anchor for s in notes if s.anchor]
    assert "421" in anchors


def test_region_catalog_kavkaz_extracts_document_links(fixture_bytes, fixture_url):
    p = _parse("kavkaz_catalog.fragment.html",
               fixture_url["kavkaz_catalog.fragment.html"], fixture_bytes)
    assert p.page_type == "region_catalog"
    assert len(p.links) >= 100  # fragment; full page has 300+


def test_decoder_handles_windows1251(fixture_bytes):
    p = parse_page("https://www.vostlit.info/",
                   fixture_bytes("home.html"), charset="windows-1251")
    # Cyrillic decoded, not mojibake
    assert "Восточная" in (p.title or "")
