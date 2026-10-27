"""Text & string normalisation for vostlit_research.

The cardinal rule of this module is: **normalisation is a derived view, never
a replacement for the original**. Every function here returns a NEW string;
callers must keep the original alongside the normalised form (the schema does
this with paired columns: ``text`` + ``text_lower``, ``original_form`` +
``normalized_form``).

Three normalisation levels are provided, in increasing aggressiveness:

    lower_cyr(s)          # Cyrillic-aware lower-case; preserves ё, ѣ, і, ѳ
    normalise_search(s)   # + fold pre-reform → modern, strip punct, collapse ws
    normalise_url(url)    # canonical URL form for de-duplication

Fuzzy matching uses stdlib :mod:`difflib` only — no external model.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Pre-reform Russian letters and their modern folds.
_PRE_REFORM = {
    "ѣ": "е", "Ѣ": "Е",
    "і": "и", "І": "И",
    "ѳ": "ф", "Ѳ": "Ф",
    "ѵ": "и", "Ѵ": "И",
    "ъ": "",  # hard sign: drop word-finally (handled in normalise_search, not here blindly)
}
# We do NOT globally fold ё→е for the "exact" level; only normalise_search does.
YO_FOLD = {"ё": "е", "Ё": "Е"}

# Word characters for tokenisation: Unicode letters + digits + apostrophe.
# NOTE: the hyphen is intentionally NOT a word char, so that
# "Джалдари-меер" tokenises into "джалдари" + "меер" — matching the way the
# FTS5 unicode61 tokenizer splits on the hyphen. This keeps normalise_search
# consistent with what is actually stored in the FTS indexes.
_WORD_RE = re.compile(r"[^\w']+", re.UNICODE)

# Geographic generic terms that should be STRIPPED from a toponym before
# fuzzy-matching its core, but kept available for context search. These are the
# terms the master prompt calls out (гора, хребет, перевал, ...) plus common
# historical/local equivalents.
GEO_GENERIC_TERMS = (
    # Russian
    "гора", "горы", "гору", "горой", "горою", "гор",
    "хребет", "хребта", "хребтом",
    "перевал", "перевала", "перевалом",
    "вершина", "вершины", "вершиной",
    "высота", "высоты",
    "урочище", "урочища",
    "ущелье", "ущелья",
    "долина", "долины",
    "река", "речки", "р.", "река",
    "озеро", "оз.",
    "село", "селение", "деревня", "аул", "кишлак", "юрт",
    "крепость", "крепости",
    "башня", "башни",
    # Common Dagestan/Caucasus geographic terms
    "меер", "маги", "кӀудияб",  # Avar forms (kept for completeness)
    # Latin/German/French generic terms found in historical scholarship
    "berg", "gebirge", "pass", "mont", "montagne", "mount", "mt", "m.",
    "height", "ridge", "peak",
)


def lower_cyr(s: str) -> str:
    """Cyrillic-aware lower-case. Python's str.lower() already handles Cyrillic
    correctly; this wrapper exists so callers express intent and so we have a
    single seam to adjust if needed (e.g. for capital Ё → ё which str.lower
    also handles)."""
    if not s:
        return ""
    return s.lower()


def fold_pre_reform(s: str) -> str:
    """Fold pre-reform Russian letters (ѣ і ѳ ѵ) to modern forms."""
    if not s:
        return ""
    return "".join(_PRE_REFORM.get(ch, ch) for ch in s)


def fold_yo(s: str) -> str:
    """Fold ё → е (case-aware)."""
    if not s:
        return ""
    return "".join(YO_FOLD.get(ch, ch) for ch in s)


def strip_punct(s: str) -> str:
    """Replace runs of non-word characters with a single space."""
    if not s:
        return ""
    return _WORD_RE.sub(" ", s).strip()


def collapse_ws(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def normalise_search(s: str) -> str:
    """Normalise free text for the FTS5 indexes.

    Order matters:
      1. NFKC unicode normalisation (compatibility forms, e.g. ﬀ → ff).
      2. fold pre-reform letters → modern.
      3. fold ё → е.
      4. lower-case.
      5. strip punctuation into spaces.
      6. collapse whitespace.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = fold_pre_reform(s)
    s = fold_yo(s)
    s = s.lower()
    s = strip_punct(s)
    s = collapse_ws(s)
    return s


def normalise_url(url: str) -> str:
    """Canonical URL form for de-duplication.

    - lower-case scheme & host
    - remove fragment
    - keep only the ``id`` query param (the site's stable identifier); drop
      tracking/noise params
    - normalise the path: keep case (the site is case-sensitive for .htm
      slugs) but strip redundant trailing slashes
    - absolute URLs only
    """
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parts = urlsplit(url)
    # keep only id query param
    qs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
          if k.lower() == "id"]
    query = urlencode(qs)
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    # canonicalise scheme to https (the site is https-only; this also makes
    # http/https variants of the same URL de-duplicate to one document).
    return urlunsplit(("https", parts.netloc.lower(), path, query, ""))


def stable_id_from_url(url: str) -> str | None:
    """Return the site's stable `id` query value if present, else the URL path."""
    parts = urlsplit(url)
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k.lower() == "id" and v:
            return v
    # bare .htm docs have no id; use the path as the stable identifier.
    return parts.path or None


# ---------------------------------------------------------------------- fuzzy

def similarity(a: str, b: str) -> float:
    """Similarity in [0,1] between two strings on their normalised forms."""
    a = normalise_search(a)
    b = normalise_search(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_candidates(
    query: str,
    candidates: list[tuple[str, Any]],
    threshold: float = 0.72,
    limit: int = 50,
) -> list[tuple[float, Any]]:
    """Return ``[(score, candidate), ...]`` above ``threshold``.

    ``candidates`` is a list of ``(text, payload)`` pairs. The score is the
    normalised-form similarity. Results are marked as CANDIDATES only — the
    caller must not treat a high score as proven identity.
    """
    q = normalise_search(query)
    out: list[tuple[float, Any]] = []
    for text, payload in candidates:
        n = normalise_search(text)
        if not n:
            continue
        score = SequenceMatcher(None, q, n).ratio()
        # also consider token-sort similarity for word-order-independent match
        ts = SequenceMatcher(None, " ".join(sorted(q.split())), " ".join(sorted(n.split()))).ratio()
        score = max(score, ts)
        if score >= threshold:
            out.append((round(score, 4), payload))
    out.sort(key=lambda x: x[0], reverse=True)
    return out[:limit]


def strip_geo_generic(name: str) -> str:
    """Return the core of a toponym with generic geographic terms removed.

    e.g. "гора Джалдари-меер" → "джалдари-меер". Used for fuzzy core matching;
    the original is never lost (caller keeps it).
    """
    if not name:
        return ""
    s = normalise_search(name)
    tokens = s.split()
    kept = [t for t in tokens if t not in GEO_GENERIC_TERMS and t.rstrip(".") not in GEO_GENERIC_TERMS]
    return collapse_ws(" ".join(kept))


# ---------------------------------------------------------------------- FTS query

_FTS_SPECIAL = re.compile(r'["*^():]')


def build_fts_query(query: str, whole_phrase: bool = False) -> str:
    """Build a safe FTS5 MATCH expression from free-form user input.

    The FTS indexes store NORMALISED text (normalise_search: lowercased,
    pre-reform folded, ё folded, hyphen-split). So the query MUST be run
    through normalise_search too, or it will not match. This function does
    that, then:
      - strips FTS5 special characters;
      - if multiword (or whole_phrase), quotes as a phrase;
      - otherwise emits the single token.
    """
    if not query:
        return ""
    q = normalise_search(query)
    if not q:
        return ""
    # strip any remaining FTS5 special chars (defensive — normalise_search
    # already removed punctuation, but be safe)
    q = _FTS_SPECIAL.sub(" ", q).strip()
    q = collapse_ws(q)
    if not q:
        return ""
    if whole_phrase or " " in q:
        return f'"{q}"'
    return q


def has_pre_reform(s: str) -> bool:
    """True if the string contains any pre-reform Russian letter."""
    return any(ch in _PRE_REFORM for ch in (s or ""))


# A 1:1 (offset-preserving) fold used for locating query terms inside the
# ORIGINAL text without destroying character positions. Every transformation
# here maps one character to exactly one character, so a match offset in the
# folded string maps directly back to the original. (ъ is kept, not dropped;
# the ъ/ъ-less mismatch is handled at the token level in the search engine,
# where each token is run through normalise_search.)
_FOLD_1TO1 = {**_PRE_REFORM, **YO_FOLD}
# fold_for_match must be a strict 1:1 character map (offset-preserving), so
# do NOT drop ъ/Ь here (their dropping is handled at the token level by the
# search engine, which normalises each token independently).
_FOLD_1TO1["ъ"] = "ъ"
_FOLD_1TO1["Ъ"] = "Ъ"
_FOLD_1TO1["ь"] = "ь"
_FOLD_1TO1["Ь"] = "Ь"


def fold_for_match(s: str) -> str:
    """Offset-preserving fold: NFKC + pre-reform + ё + lower (1:1 char map).

    Used by the search engine to locate a normalised query inside original
    text and then cut a snippet whose offsets are valid in the ORIGINAL.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    out_chars: list[str] = []
    for ch in s:
        out_chars.append(_FOLD_1TO1.get(ch, ch))
    return "".join(out_chars).lower()
