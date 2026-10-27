"""HTML parser for Vostlit.info pages.

Every selector in this module is **verified** against real pages — see
``docs/SITE_AUDIT.md`` (sections 5–9) for the evidence. The parser branches on
two signals:

  1. the URL suffix (``.phtml`` = site-chrome flavor vs ``.htm`` = bare flavor)
  2. structural markers (presence of ``#main``, ``#dann``, ``<title>`` shape)

The parser NEVER destroys original spelling. It produces structured sections
that the store layer writes verbatim; normalisation happens later, only for
the FTS5 indexes.

Output type: :class:`ParsedPage`. Use :func:`parse_page` for the dispatch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

# --- verified colours (see SITE_AUDIT.md §6.2/§7.1) -----------------------
COLOR_PAGE_BREAK = "#800000"   # maroon [N]  -> print-edition page break
COLOR_CHAPTER = "#ff0000"      # red {N}     -> source-edition chapter (or editorial gloss in .htm)
COLOR_FOOTNOTE_BLUE = "#0000ff"  # blue <sup>N</sup> footnote ref
COLOR_CITATION_HTM = "#800040"  # maroon citation block in bare .htm docs
COLOR_HEAD_GREEN = "#336633"    # green headings in alpha index / collection index


@dataclass
class Section:
    section_type: str
    heading: str | None = None
    text: str | None = None
    page_number: str | None = None
    anchor: str | None = None
    source_url: str | None = None


@dataclass
class Link:
    url: str
    label: str
    kind: str = "document"  # document|region|letter|year|image|notes|part|external


@dataclass
class ImageRef:
    url: str
    label: str
    size_note: str | None = None


@dataclass
class ParsedPage:
    page_type: str = "unknown"
    title: str | None = None
    author: str | None = None
    translator: str | None = None
    editor: str | None = None
    work_title: str | None = None
    publication_title: str | None = None
    publication_year: str | None = None
    original_creation_date: str | None = None
    region: str | None = None
    collection: str | None = None
    source_type: str | None = None
    language: str | None = None
    description: str | None = None
    bibliography: str | None = None
    citation: str | None = None
    extracted_text: str | None = None
    extraction_method: str | None = None
    sections: list[Section] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    images: list[ImageRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------- helpers

def decode_html(raw: bytes, declared_charset: str | None = None) -> str:
    """Decode raw bytes using the site's windows-1251 encoding.

    The server always sends ``Content-Type: text/html; charset=windows-1251``
    (verified in SITE_AUDIT.md §3). We trust the server header over any
    in-page <meta>, because some pages have contradictory/missing metas.
    """
    enc = (declared_charset or "windows-1251").lower()
    if enc in ("windows-1251", "cp1251"):
        return raw.decode("windows-1251", errors="replace")
    if enc in ("utf-8", "utf8"):
        return raw.decode("utf-8", errors="replace")
    # default: the site is 1251
    return raw.decode("windows-1251", errors="replace")


def _make_soup(html: str) -> BeautifulSoup:
    # lxml is faster and available; fall back to stdlib html.parser.
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        return BeautifulSoup(html, "html.parser")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _color_of(tag: Tag) -> str | None:
    f = tag.find_parent("font")
    if f is None:
        # some markers wrap the font inside strong
        for p in tag.parents:
            if isinstance(p, Tag) and p.name == "font" and p.get("color"):
                return str(p["color"]).strip().lower()
            if isinstance(p, Tag) and p.name in ("div", "body"):
                break
        return None
    return str(f.get("color") or "").strip().lower() or None


_PAGE_BREAK_RE = re.compile(r"\[(\d+)\]")
_CHAPTER_RE = re.compile(r"\{(\d+)\]")


def _is_central(p: Tag) -> bool:
    a = (p.get("align") or "").lower()
    return a in ("center", "centre", "middle")


def _is_http_href(href: str) -> bool:
    """True for absolute http(s) URLs and relative paths; False for mailto/javascript/etc."""
    if not href:
        return False
    h = href.strip().lower()
    if h.startswith(("mailto:", "javascript:", "tel:", "ftp:", "data:")):
        return False
    return True


# ---------------------------------------------------------------------- dispatch

def classify(url: str, soup: BeautifulSoup, raw_size: int) -> str:
    """Return a page_type string. See SITE_AUDIT.md §5."""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    host = (parts.netloc or "").lower()
    path = (parts.path or "/").lower()
    has_main = soup.find(id="main") is not None
    title = (soup.title.string or "").strip() if soup.title else ""
    # homepage: bare path on the site root
    if path in ("", "/") and host in ("www.vostlit.info", "vostlit.info"):
        return "home"
    if "/haupt-dateien/index-dateien/" in path:
        return "alpha_index"
    if "/texts/dokumenty/index.phtml" in path:
        return "documents_hub"
    if "/common/itogi" in path:
        return "itogi_index"
    if "primtext" in path:
        return "notes_page"
    if "karten" in path:
        return "image_gallery"
    # collection index .htm
    if path.endswith("/index.htm") and not has_main:
        return "collection_index"
    # region catalog: /Texts/Dokumenty/<region>.html, no #main
    if re.search(r"/texts/dokumenty/[^/]+\.(html?|htm)$", path) and not has_main:
        return "region_catalog"
    if path.endswith(".phtml"):
        return "document_text"
    if path.endswith((".htm", ".html")):
        return "document_text"  # bare flavor
    if has_main:
        return "document_text"
    return "unknown"


def parse_page(url: str, raw_or_text: bytes | str, *, charset: str | None = None) -> ParsedPage:
    """Parse a fetched page. Accepts raw bytes (preferred) or a decoded str."""
    if isinstance(raw_or_text, bytes):
        text = decode_html(raw_or_text, charset)
    else:
        text = raw_or_text
    soup = _make_soup(text)
    ptype = classify(url, soup, len(text))
    parsed = ParsedPage(page_type=ptype, extraction_method=ptype)
    if ptype == "home":
        _parse_home(url, soup, parsed)
    elif ptype == "alpha_index":
        _parse_alpha_index(url, soup, parsed)
    elif ptype == "documents_hub":
        _parse_documents_hub(url, soup, parsed)
    elif ptype == "region_catalog":
        _parse_region_catalog(url, soup, parsed)
    elif ptype == "itogi_index":
        _parse_itogi(url, soup, parsed)
    elif ptype == "notes_page":
        _parse_notes_page(url, soup, parsed)
    elif ptype == "image_gallery":
        _parse_image_gallery(url, soup, parsed)
    elif ptype == "collection_index":
        _parse_collection_index(url, soup, parsed)
    elif ptype == "document_text":
        if soup.find(id="main") is not None:
            _parse_phtml_doc(url, soup, parsed)
        else:
            _parse_htm_doc(url, soup, parsed)
    else:
        parsed.warnings.append(f"unclassified page: {url}")
    # drop non-http links (mailto:, javascript:, etc.) once, at the boundary
    parsed.links = [lk for lk in parsed.links if lk.url.lower().startswith(("http://", "https://"))]
    return parsed


# ---------------------------------------------------------------------- home

def _parse_home(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    p.title = _clean(soup.title.string) if soup.title else "Восточная Литература"
    main = soup.find(id="main")
    seen = set()
    if main:
        for a in main.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if "/Texts/" in href and href not in seen:
                seen.add(href)
                p.links.append(Link(href, _clean(a.get_text()), "document"))
    p.extracted_text = _clean(main.get_text(" ")) if main else ""


# ---------------------------------------------------------------------- alpha index

def _parse_alpha_index(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    p.title = _clean(soup.title.string) if soup.title else None
    main = soup.find(id="main") or soup.body
    if main is None:
        p.warnings.append("no #main in alpha_index")
        return
    for para in main.find_all("p", recursive=True):
        # the CAPS header is the first non-empty text node; links are parts
        first_text = ""
        for child in para.descendants:
            if isinstance(child, NavigableString):
                t = _clean(str(child))
                if t:
                    first_text = t
                    break
        for a in para.find_all("a", href=True):
            href = urljoin(url, a["href"])
            label = _clean(a.get_text())
            kind = "part"
            if href.endswith((".htm", ".html")) and "frame" in href.lower():
                kind = "part"
            p.links.append(Link(href, label, kind))
        if first_text and not para.find_all("a", href=True):
            # header-only paragraph
            p.sections.append(Section("heading", heading=first_text))
    p.extracted_text = _clean(main.get_text(" "))


# ---------------------------------------------------------------------- documents hub

def _parse_documents_hub(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    p.title = _clean(soup.title.string) if soup.title else None
    main = soup.find(id="main") or soup.body
    if main:
        for a in main.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if "/Texts/Dokumenty/" in href:
                p.links.append(Link(href, _clean(a.get_text()), "region"))


# ---------------------------------------------------------------------- region catalog

def _parse_region_catalog(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    p.title = _clean(soup.title.string) if soup.title else None
    body = soup.body or soup
    for table in body.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            for td in cells:
                a = td.find("a", href=True)
                if a:
                    href = urljoin(url, a["href"])
                    label = _clean(a.get_text())
                    rest = _clean(td.get_text(" "))
                    p.links.append(Link(href, label or rest, "document"))
    # the page itself may have a heading
    for big in body.find_all(["h1", "h2", "p"]):
        t = _clean(big.get_text())
        if t and len(t) < 200 and not big.find("a"):
            p.sections.append(Section("heading", heading=t))
            break
    p.extracted_text = _clean(body.get_text(" "))


# ---------------------------------------------------------------------- itogi

def _parse_itogi(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    p.title = _clean(soup.title.string) if soup.title else None
    main = soup.find(id="main") or soup.body
    if main:
        for a in main.find_all("a", href=True):
            p.links.append(Link(urljoin(url, a["href"]), _clean(a.get_text()), "year"))


# ---------------------------------------------------------------------- .phtml doc

def _parse_phtml_doc(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    main = soup.find(id="main")
    if main is None:
        p.warnings.append("no #main in phtml doc; falling back to body")
        main = soup.body or soup
    # breadcrumb title: AUTHOR->WORK->PART
    if soup.title:
        crumb = _clean(soup.title.string)
        p.source_metadata["breadcrumb"] = crumb
        parts = [x.strip() for x in crumb.split("->")]
        if len(parts) >= 1:
            p.author = parts[0] or None
        if len(parts) >= 2:
            p.work_title = parts[1] or None
        if len(parts) >= 3:
            p.title = crumb
        else:
            p.title = crumb or None
    # h4 author, h2 work (override breadcrumb if present, more reliable)
    h4 = main.find("h4")
    if h4:
        p.author = _clean(h4.get_text()) or p.author
    h2 = main.find("h2")
    if h2:
        p.work_title = _clean(h2.get_text()) or p.work_title
    if not p.title:
        p.title = p.work_title or p.author

    # citation block #dann (NESTED in #main — must extract before body)
    dann = main.find(id="dann")
    citation_text = ""
    if dann is not None:
        citation_text = _clean(dann.get_text(" "))
        # the publication line is ONLY the "Текст воспроизведен по изданию: ..."
        # part — everything from there up to the first "©" (the © copyright
        # lines follow and must NOT pollute publication_title / publication_year).
        m = re.search(r"Текст\s+воспроизведен по изданию:\s*(.+?)(?:\s*©|$)", citation_text or "")
        pub_line = m.group(1).strip() if m else None
        if pub_line:
            p.publication_title = pub_line
            years = re.findall(r"\b(1[5-9]\d{2}|20\d{2})\b", pub_line)
            if years:
                # the LAST year is normally the actual publication year of the
                # edition being reproduced (journal citations put the document
                # date first, e.g. "... 1792 г. // Исторический архив. 2003").
                p.publication_year = years[-1]
            p.citation = f"Текст воспроизведен по изданию: {pub_line}"
        else:
            p.citation = citation_text or None
        # translator line "(пер. ...)" usually sits in the © block
        tm = re.search(r"\(пер\.\s*([^)]+)\)", citation_text or "")
        if tm:
            p.translator = tm.group(1).strip()
        dann.extract()
    else:
        p.warnings.append("no #dann citation block found")

    # walk #main children in document order -> sections
    seq = 0
    body_chunks: list[str] = []

    def emit(stype: str, **kw: Any) -> None:
        nonlocal seq
        seq += 1
        p.sections.append(Section(stype, **kw))

    inline_notes_h5 = main.find("h5", string=re.compile(r"^\s*Комментарии\s*$"))
    # If inline notes exist, split: body = before h5; notes = h5's following <p> siblings
    notes_boundary = inline_notes_h5

    for el in main.descendants:
        if not isinstance(el, Tag):
            continue
        if notes_boundary is not None and el is notes_boundary:
            break
        if el.name != "p":
            continue
        # skip if this <p> is inside an already-processed nested structure
        if el.find_parent(["table"]):
            continue
        align = (el.get("align") or "").lower()
        txt = _clean(el.get_text(" "))
        if not txt:
            continue
        # headings: centered <p> with <b>/<strong> and short
        if _is_central(el) and (el.find("b") or el.find("strong")) and len(txt) < 200:
            emit("heading", heading=txt, text=txt)
            body_chunks.append(txt)
            continue
        # page-break / chapter markers within this paragraph
        for font in el.find_all("font"):
            col = str(font.get("color") or "").strip().lower()
            inner = _clean(font.get_text())
            if col == COLOR_PAGE_BREAK:
                m = _PAGE_BREAK_RE.search(inner)
                if m:
                    emit("page_break", text=inner, page_number=m.group(1))
            elif col == COLOR_CHAPTER:
                m = _CHAPTER_RE.search(inner)
                if m:
                    emit("chapter_marker", text=inner, page_number=m.group(1))
        emit("body", text=txt)
        body_chunks.append(txt)

    # inline notes section
    if inline_notes_h5 is not None:
        for sib in inline_notes_h5.find_next_siblings("p"):
            txt = _clean(sib.get_text(" "))
            if not txt:
                continue
            # note number is leading <strong>N</strong>
            strong = sib.find("strong")
            anchor = None
            if strong:
                nm = re.match(r"\s*(\d+)", strong.get_text())
                if nm:
                    anchor = nm.group(1)
            emit("note", text=txt, anchor=anchor)

    p.extracted_text = "\n\n".join(body_chunks).strip() or None
    # external links to notes pages (primtext) and other parts
    for a in main.find_all("a", href=True):
        href = urljoin(url, a["href"])
        label = _clean(a.get_text())
        if "primtext" in href:
            p.links.append(Link(href, label or "Комментарии", "notes"))
        elif "/Texts/" in href:
            p.links.append(Link(href, label, "part"))
    # bibliography = the publication_title / citation block
    if citation_text:
        emit("bibliography", text=citation_text)
        p.bibliography = citation_text


# ---------------------------------------------------------------------- .htm bare doc

def _parse_htm_doc(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    body = soup.body or soup
    p.warnings.append("bare .htm document (no site chrome)")
    # title: first centered <p> with <strong><font color="#000000">
    title_set = False
    seq = 0
    body_chunks: list[str] = []

    def emit(stype: str, **kw: Any) -> None:
        nonlocal seq
        seq += 1
        p.sections.append(Section(stype, **kw))

    # find the <hr/> that precedes the Коммент. block, if any
    hrs = body.find_all("hr")
    notes_hr = hrs[0] if hrs else None

    # title block
    first_center = body.find("p", align=re.compile(r"^center$", re.I))
    if first_center:
        t = _clean(first_center.get_text())
        if t:
            p.title = t
            p.work_title = t
            title_set = True
            emit("heading", heading=t, text=t)
            body_chunks.append(t)
        # subtitle (second centered <p>) often carries the document date
        sub = first_center.find_next_sibling("p", align=re.compile(r"^center$", re.I))
        if sub is not None:
            stxt = _clean(sub.get_text())
            if stxt and stxt != t:
                ym = re.findall(r"\b(1[5-9]\d{2}|20\d{2})\b", stxt)
                if ym:
                    p.original_creation_date = ym[-1]
                p.source_metadata["subtitle"] = stxt
    if not title_set and soup.title:
        p.title = _clean(soup.title.string) or None

    # body: all <p> before notes_hr (or all <p> if no hr)
    for el in body.find_all("p"):
        if notes_hr is not None and el in notes_hr.find_all_next("p"):
            break
        if el is first_center:
            # already emitted as heading; but a second centered <p> (subtitle) is fine
            continue
        txt = _clean(el.get_text(" "))
        if not txt:
            continue
        align = (el.get("align") or "").lower()
        if align == "right":
            # archive ID / signature
            p.source_metadata["archive_signature"] = txt
            emit("note", text=txt, heading="archive_signature")
            continue
        if _is_central(el):
            emit("heading", heading=txt, text=txt)
            body_chunks.append(txt)
            continue
        # editorial glosses in red
        for font in el.find_all("font", color=re.compile(r"^#?ff0000$", re.I)):
            gloss = _clean(font.get_text())
            if gloss:
                emit("note", text=gloss, heading="editorial_gloss")
        emit("body", text=txt)
        body_chunks.append(txt)

    # notes after <hr/> + <big>Комментарии</big>
    if notes_hr is not None:
        cur = notes_hr.find_next()
        in_notes = False
        while cur is not None:
            if isinstance(cur, Tag) and cur.name == "p":
                txt = _clean(cur.get_text(" "))
                if txt:
                    # citation block: small + font #800040
                    if cur.find("font", color=re.compile(r"^#?800040$", re.I)):
                        emit("bibliography", text=txt)
                        if "Текст воспроизведен по изданию" in txt:
                            # the edition line (NOT the © copyright lines)
                            mm = re.search(r"Текст\s+воспроизведен по изданию:\s*(.+)", txt)
                            if mm:
                                pub_line = mm.group(1).strip()
                                p.publication_title = pub_line
                                p.citation = txt  # keep the full "Текст воспроизведен..." line
                                years = re.findall(r"\b(1[5-9]\d{2}|20\d{2})\b", pub_line)
                                if years:
                                    p.publication_year = years[-1]
                            p.bibliography = (p.bibliography + "\n" + txt) if p.bibliography else txt
                        else:
                            # a © copyright line; accumulate but don't overwrite citation
                            p.bibliography = (p.bibliography + "\n" + txt) if p.bibliography else txt
                            if not p.citation:
                                p.citation = txt
                    elif cur.find("big") and "коммент" in txt.lower():
                        in_notes = True
                        emit("heading", heading=txt, text=txt)
                    elif in_notes:
                        nm = re.match(r"\s*(\d+)[\.\)]", txt)
                        emit("note", text=txt, anchor=nm.group(1) if nm else None)
                    else:
                        emit("body", text=txt)
                        body_chunks.append(txt)
            cur = cur.find_next()

    p.extracted_text = "\n\n".join(body_chunks).strip() or None
    if not p.author:
        p.author = None
    # links: none typically, but collect any /Texts/ links
    for a in body.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if "/Texts/" in href:
            p.links.append(Link(href, _clean(a.get_text()), "part"))


# ---------------------------------------------------------------------- notes page

def _parse_notes_page(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    p.title = _clean(soup.title.string) if soup.title else "Комментарии"
    main = soup.find(id="main") or soup.body
    if main is None:
        return
    h5 = main.find("h5")
    start = h5 if h5 is not None else main
    for sib in (start.find_next_siblings("p") if h5 else main.find_all("p")):
        txt = _clean(sib.get_text(" "))
        if not txt:
            continue
        strong = sib.find("strong")
        anchor = None
        if strong:
            nm = re.match(r"\s*(\d+)", strong.get_text())
            if nm:
                anchor = nm.group(1)
        p.sections.append(Section("note", text=txt, anchor=anchor, source_url=url))
    p.extracted_text = "\n\n".join(s.text for s in p.sections if s.text).strip() or None


# ---------------------------------------------------------------------- image gallery

def _parse_image_gallery(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    main = soup.find(id="main") or soup.body
    p.title = _clean(soup.title.string) if soup.title else None
    if main is None:
        return
    for a in main.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.(jpe?g|png|gif)$", href, re.I):
            img_url = urljoin(url, href)
            label = _clean(a.get_text())
            big = a.find_next("big")
            size = _clean(big.get_text()) if big else None
            p.images.append(ImageRef(img_url, label, size))
            p.sections.append(Section("caption", heading=label, text=label, source_url=img_url))
    p.extracted_text = _clean(main.get_text(" ")) or None


# ---------------------------------------------------------------------- collection index

def _parse_collection_index(url: str, soup: BeautifulSoup, p: ParsedPage) -> None:
    body = soup.body or soup
    # big title
    for para in body.find_all("p", align=re.compile(r"^center$", re.I)):
        font = para.find("font", color=re.compile(r"^#?000000$", re.I))
        if font and font.get("size") in ("6", "5"):
            p.title = _clean(font.get_text())
            p.collection = p.title
            break
    if not p.title and soup.title:
        p.title = _clean(soup.title.string)
    # each sub-work <p>: first a size=4 green font (title), then <a> parts
    for para in body.find_all("p"):
        title_font = para.find("font", attrs={"size": "4"})
        if title_font:
            subwork = _clean(title_font.get_text())
            if subwork:
                p.sections.append(Section("heading", heading=subwork, text=subwork))
        for a in para.find_all("a", href=True):
            href = urljoin(url, a["href"])
            label = _clean(a.get_text())
            p.links.append(Link(href, label, "part"))
    p.extracted_text = _clean(body.get_text(" ")) or None
