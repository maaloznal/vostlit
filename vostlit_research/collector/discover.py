"""Discovery: turn hub/index/catalog pages into a queue of document URLs.

Discovery is READ-ONLY against the site (it fetches hub/index pages but does
not fetch document text). It records every discovered URL in ``crawl_log``
and, where useful, pre-creates ``documents`` rows with status ``discovered``
so the inventory is queryable before any text is fetched.

Supported seeds:
  * the homepage (featured links)
  * the documents hub -> region catalogs
  * a specific region catalog (e.g. ``kavkaz.html`` for the Caucasus)
  * alphabetical author index pages (one per Cyrillic letter)
  * explicit user-supplied URLs
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from ..config import Config
from ..db import Database
from .. import textnorm
from .http import HttpClient
from .parser import parse_page

# Known region slugs (verified in SITE_AUDIT.md §4.1/§10). Map a friendly name
# to the catalog filename under /Texts/Dokumenty/.
REGIONS = {
    "caucasus": "kavkaz.html",
    "kavkaz": "kavkaz.html",
    "кавказ": "kavkaz.html",
    "russia": "russ.htm",
    "russ": "russ.htm",
    "crimea": "krym.html",
    "krym": "krym.html",
    "middle_asia": "m.asien.htm",
    "turkestan": "turk.htm",
}

# Cyrillic letter slugs used in the alphabetical index (verified, ids 2041..2069).
ALPHA_LETTERS = {
    "A": "A", "B": "B", "V": "V", "G": "G", "D": "D", "E": "E",
    "ZH": "ZH", "Z": "Z", "I": "I", "IJ": "IJ", "K": "K", "L": "L",
    "M": "M", "N": "N", "O": "O", "P": "P", "R": "R", "S": "S",
    "T": "T", "U": "U", "F": "F", "H": "H", "TZ": "TZ", "CH": "CH",
    "SCH": "SCH", "EE": "EE", "JU": "JU", "JA": "JA",
}
ALPHA_IDS = {  # verified id query values for each letter
    "A": 2041, "B": 2042, "V": 2043, "G": 2044, "D": 2045, "E": 2046,
    "ZH": 2047, "Z": 2048, "I": 2049, "IJ": 2050, "K": 2051, "L": 2052,
    "M": 2053, "N": 2054, "O": 2055, "P": 2056, "R": 2057, "S": 2058,
    "T": 2059, "U": 2060, "F": 2061, "H": 2062, "TZ": 2063, "CH": 2064,
    "SCH": 2065, "EE": 2067, "JU": 2068, "JA": 2069,
}


def _is_doc_url(url: str) -> bool:
    """True if a URL points at a content page worth inventorying.

    Previously required `/texts/` in the path, which silently dropped 5
    classes of entry points confirmed on the live site (SITE_COVERAGE_AUDIT.md §2):
      - /common/            (itogi yearly archive, lib_uk bibliographic indexes)
      - /Repertorium/       (682 European-medieval docs, verified live)
      - /MGH/               (Monumenta Germaniae Historica series)
      - /MPH/               (Monumenta Poloniae Historica series)
    Each of these is a vostlit.info-internal document collection whose pages
    end in .phtml/.htm/.html — exactly the same shape as /texts/. They are
    allowlisted in config.allowed_sections, so the path is in-scope; the
    document-shape check (file extension) is what matters here.
    """
    p = urlsplit(url)
    path = p.path.lower()
    # accept any of the known in-scope document roots
    if not any(root in path for root in (
        "/texts/", "/common/", "/repertorium/", "/mgh/", "/mph/",
    )):
        return False
    # document-ish files (exclude directory indexes without an extension —
    # those are catalog pages, not documents, and are harvested separately)
    return path.endswith((".phtml", ".htm", ".html"))


def _record_discovered(db: Database, url: str, page_type: str | None) -> None:
    canonical = textnorm.normalise_url(url)
    with db.conn:
        row = db.conn.execute(
            "SELECT id, page_type FROM documents WHERE canonical_url = ?", (canonical,)
        ).fetchone()
        if row is None:
            db.conn.execute(
                """INSERT INTO documents
                   (canonical_url, stable_id, page_type, first_seen_at, last_checked_at, status)
                   VALUES (?,?,?,?,?, 'discovered')""",
                (canonical, textnorm.stable_id_from_url(canonical), page_type,
                 db.now(), db.now()),
            )
        elif page_type and not row["page_type"]:
            # update page_type if we now know it and didn't before
            db.conn.execute(
                "UPDATE documents SET page_type = ? WHERE canonical_url = ?",
                (page_type, canonical),
            )
        db.conn.execute(
            "INSERT INTO crawl_log (url, canonical_url, fetched_at, action) VALUES (?,?,?, 'discovered')",
            (url, canonical, db.now()),
        )


def discover(
    config: Config,
    db: Database,
    http: HttpClient,
    *,
    regions: list[str] | None = None,
    letters: list[str] | None = None,
    seeds: list[str] | None = None,
    include_home: bool = False,
    max_discover: int | None = None,
) -> list[str]:
    """Return a de-duplicated list of discovered document URLs.

    Records each in crawl_log and (as a side effect) creates ``discovered``
    document rows. Does NOT fetch document text. Honours ``max_discover``:
    once that many URLs have been recorded, discovery stops cleanly (the cap
    is checked via a return value, not an exception, so per-link errors in
    the harvester cannot accidentally bypass it).
    """
    found: list[str] = []
    seen: set[str] = set()
    state = {"stop": False}

    def add(url: str, ptype: str | None) -> bool:
        """Record a URL. Returns False when the cap is reached (caller should stop)."""
        canonical = textnorm.normalise_url(url)
        if canonical in seen or not _is_doc_url(canonical):
            return True  # not a new doc, keep going
        seen.add(canonical)
        found.append(canonical)
        try:
            _record_discovered(db, canonical, ptype)
        except Exception:  # noqa: BLE001
            pass  # a DB hiccup on one URL must not abort discovery
        if max_discover and len(found) >= max_discover:
            state["stop"] = True
            return False
        return True

    def harvest(url: str) -> None:
        if state["stop"]:
            return
        res = http.fetch(url)
        parsed = parse_page(url, res.content, charset=_charset(res.content_type))
        for link in parsed.links:
            if not add(link.url, _guess_page_type(link.url)):
                return

    # explicit seeds first
    for s in seeds or []:
        if state["stop"]:
            break
        if _is_catalog_or_index(s):
            harvest(s)
        else:
            add(s, None)
    # home
    if include_home and not state["stop"]:
        harvest(config.base_url)
    # regions
    for r in regions or []:
        if state["stop"]:
            break
        slug = REGIONS.get(r.lower(), r if r.endswith((".html", ".htm")) else r + ".html")
        url = urljoin(config.base_url, f"/Texts/Dokumenty/{slug}")
        harvest(url)
    # letters
    for L in letters or []:
        if state["stop"]:
            break
        key = L.upper()
        if key in ALPHA_LETTERS:
            url = urljoin(
                config.base_url,
                f"/haupt-Dateien/index-Dateien/{ALPHA_LETTERS[key]}.phtml?id={ALPHA_IDS[key]}",
            )
            harvest(url)
    return found


def _is_catalog_or_index(url: str) -> bool:
    """True if the URL is a hub/catalog/index PAGE (to be harvested for links),
    not a document text page (to be stored directly).

    Bug fix: the previous version matched ANY .htm/.html under /Texts/Dokumenty/
    (including text1.htm deep in /Kavkaz/XIX/1860-1880/Tri_mesjac_dag_otrjad/),
    which caused discover() to harvest the document's links instead of storing
    it as a document — silently dropping it from the corpus.

    A real region catalog is a file DIRECTLY in /Texts/Dokumenty/ (e.g.
    /Texts/Dokumenty/kavkaz.html), not in a nested subdirectory. We detect
    that by checking the path has exactly the form
    /texts/dokumenty/<filename>.html? (no further path segments after the
    region filename).
    """
    import re
    p = urlsplit(url).path.lower()
    if p == "/":
        return True
    if "/haupt-dateien/index-dateien/" in p:
        return True
    if "/texts/dokumenty/index.phtml" in p:
        return True
    if p.endswith("/index.htm"):
        return True
    # region catalog: /texts/dokumenty/<region>.html? — exactly one segment
    # after /texts/dokumenty/ and it ends in .html/.htm (NOT a nested doc path)
    if re.match(r"^/texts/dokumenty/[^/]+\.(html?|htm)$", p):
        return True
    return False


def _guess_page_type(url: str) -> str | None:
    p = urlsplit(url).path.lower()
    if "primtext" in p:
        return "notes_page"
    if "karten" in p:
        return "image_gallery"
    if p.endswith("/index.htm"):
        return "collection_index"
    if p.endswith(".phtml"):
        return "document_text"
    if p.endswith((".htm", ".html")):
        return "document_text"
    return None


def _charset(content_type: str) -> str | None:
    if "charset=" in (content_type or "").lower():
        return content_type.split("charset=", 1)[1].split(";")[0].strip()
    return "windows-1251"
