"""VariantExpander: automatic generation of spelling variants for a toponym.

The single biggest quality leap for the skill. Before this, the agent had to
manually guess variants (Гадари/Гадаръ/Кадириъ/...) and often missed them.
Now a single toponym expands to 20–80 candidates covering:

  1. Pre-reform Russian (ъ, ѣ→е, і→и, ѳ→ф, ѵ→и)
  2. ё↔е folding
  3. Case variants
  4. Caucasian phonetic alternations (Г↔К, Г↔Къ, Гь↔ГI, К↔Къ, х↔г)
  5. Transliteration forms (German dj/gj, French, English)
  6. Generic geographic term stripping + re-attachment
  7. Edit-distance OCR candidates (Levenshtein ≤2 against the variant dict)
  8. Suffix variations (ъ, -и, -ий, -ы, -ик, -иб)

Each variant is tagged with its derivation path so the agent can explain WHY
a form was searched. Nothing here MERGES entities — it only generates search
candidates. Identity is always decided by the EvidenceLinker with context.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class Variant:
    form: str
    derivation: str  # human-readable explanation of how this form was derived
    confidence: str = "candidate"  # candidate | likely | exact


@dataclass
class VariantSet:
    original: str
    core: str  # generic terms stripped
    variants: list[Variant] = field(default_factory=list)

    def forms(self) -> list[str]:
        """De-duplicated list of forms (including original + core)."""
        seen = set()
        out = []
        for v in [self.original, self.core] + [x.form for x in self.variants]:
            f = v.strip()
            if f and f.lower() not in seen:
                seen.add(f.lower())
                out.append(f)
        return out

    def by_confidence(self, conf: str) -> list[str]:
        return [v.form for v in self.variants if v.confidence == conf]


# ----------------------------------------------------------------------
# generic geographic terms (Dagestan/Caucasus + pan-Russian + European)
# ----------------------------------------------------------------------

GEO_GENERICS_RU = [
    "гора", "горы", "гору", "горой", "горою", "гор",
    "хребет", "хребта", "хребтом",
    "перевал", "перевала", "перевалом",
    "вершина", "вершины", "вершиной",
    "высота", "высоты",
    "урочище", "урочища",
    "ущелье", "ущелья",
    "долина", "долины",
    "река", "речки", "р",
    "озеро", "оз",
    "село", "селение", "сел", "деревня", "аул", "кишлак", "юрт",
    "крепость", "крепости",
    "башня", "башни",
    "меер",  # Dagestan mountain term (source-attested)
]
GEO_GENERICS_LATIN = [
    "berg", "gebirge", "pass", "mont", "montagne", "mount", "mt", "m.",
    "height", "ridge", "peak", "village", "selo",
]
GEO_GENERICS = tuple(GEO_GENERICS_RU + GEO_GENERICS_LATIN)


# ----------------------------------------------------------------------
# Caucasian phonetic alternations
# These are well-attested in Dagestan/Caucasus linguistics:
#   Г/К alternation (voicing), Къ/К (ejective), Гь/ГI (pharyngeal),
#   х/г, т/д, п/б, ц/ч. Applied conservatively — each yields a candidate,
#   identity is never auto-merged.
# ----------------------------------------------------------------------

CAUCASIAN_PHONETIC = {
    "г": ["к", "къ", "гъ", "гь", "гI"],
    "к": ["г", "къ", "кI"],
    "х": ["г", "хъ", "хь", "хI"],
    "д": ["т", "тI"],
    "т": ["д", "тI"],
    "б": ["п", "пI"],
    "п": ["б", "пI"],
    "ц": ["ч", "цI"],
    "ч": ["ц", "чI"],
    "ж": ["ш", "жж"],
}

# German/French/English transliteration pairs for Russian Cyrillic
TRANSLIT_PAIRS = {
    "дж": ["dj", "gj", "zh"],
    "гъ": ["gh", "g"],
    "къ": ["kh", "q", "k"],
    "гь": ["gh", "g"],
    "гI": ["g", "gh", "ʿ"],
    "хъ": ["kh", "qh"],
    "хь": ["kh", "h"],
    "а": ["a", "ä"],
    "и": ["i", "y", "ij"],
    "й": ["j", "y", "i"],
    "ы": ["y", "ı"],
    "э": ["e", "è"],
    "ю": ["ju", "yu"],
    "я": ["ja", "ya"],
}

PRE_REFORM = {"ѣ": "е", "Ѣ": "Е", "і": "и", "І": "И", "ѳ": "ф", "Ѳ": "Ф", "ѵ": "и", "Ѵ": "И"}
YO_FOLD = {"ё": "е", "Ё": "Е"}


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _fold_prereform(s: str) -> str:
    return "".join(PRE_REFORM.get(c, c) for c in s)


def _fold_yo(s: str) -> str:
    return "".join(YO_FOLD.get(c, c) for c in s)


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = _fold_prereform(s)
    s = _fold_yo(s)
    return s.lower()


def _strip_geo_generic(name: str) -> str:
    """Remove generic geographic terms, return the toponym core."""
    s = _normalize(name)
    tokens = s.split()
    kept = [t for t in tokens if t not in GEO_GENERICS and t.rstrip(".") not in GEO_GENERICS]
    return " ".join(kept).strip()


def _suffix_variants(core: str) -> list[tuple[str, str]]:
    """Generate suffix variations (ъ, -и, -ий, -ы, -ик, -иб, -е)."""
    out: list[tuple[str, str]] = []
    base = core.rstrip("ъъь")
    for suf, why in [("ъ", "pre-reform hard sign"),
                     ("и", "nominative plural / locative"),
                     ("ий", "adjectival"),
                     ("ы", "plural"),
                     ("ик", "diminutive"),
                     ("иб", "arabic definite article (e.g. Гадариб)"),
                     ("е", "prepositional")]:
        if not core.endswith(suf):
            out.append((base + suf, f"suffix {why}"))
    return out


def _phonetic_variants(core: str) -> list[tuple[str, str]]:
    """Generate Caucasian phonetic alternation candidates."""
    out: list[tuple[str, str]] = []
    for i, ch in enumerate(core):
        ch_lower = ch.lower()
        if ch_lower in CAUCASIAN_PHONETIC:
            for alt in CAUCASIAN_PHONETIC[ch_lower]:
                variant = core[:i] + alt + core[i+1:]
                why = f"phonetic {ch}↔{alt}"
                out.append((variant, why))
    return out


def _translit_variants(core: str) -> list[tuple[str, str]]:
    """Generate Latin transliteration candidates (for German/French editions)."""
    out: list[tuple[str, str]] = []
    for cyr, lats in TRANSLIT_PAIRS.items():
        if cyr in core.lower():
            for lat in lats:
                variant = re.sub(cyr, lat, core, flags=re.IGNORECASE)
                if variant != core:
                    out.append((variant, f"transliteration {cyr}→{lat}"))
    return out


# ----------------------------------------------------------------------
# public API
# ----------------------------------------------------------------------

def expand_variants(name: str, *, include_ocr: bool = True,
                    variant_dict: list[str] | None = None) -> VariantSet:
    """Expand a toponym into a full variant set.

    Args:
        name: the toponym as given (e.g. "село Гадари" or "гора Джалдари-меер")
        include_ocr: if True, generate edit-distance OCR candidates against
                     the variant dictionary (needs variant_dict)
        variant_dict: list of known forms from name_variants table, for OCR
                      candidate generation

    Returns:
        VariantSet with original, core, and a list of Variant objects.
    """
    vs = VariantSet(original=name, core=_strip_geo_generic(name))
    core = vs.core

    # 1. exact original + core (highest confidence)
    vs.variants.append(Variant(name, "original form", "exact"))
    if core and core != name.lower():
        vs.variants.append(Variant(core, "generic terms stripped", "likely"))

    # 2. pre-reform + ё fold of the core
    norm = _normalize(core)
    if norm != core.lower():
        vs.variants.append(Variant(norm, "pre-reform + ё folded + lowercased", "likely"))

    # 3. suffix variants
    for form, why in _suffix_variants(core):
        vs.variants.append(Variant(form, why, "candidate"))

    # 4. phonetic alternations
    for form, why in _phonetic_variants(core):
        vs.variants.append(Variant(form, why, "candidate"))

    # 5. transliteration
    for form, why in _translit_variants(core):
        vs.variants.append(Variant(form, why, "candidate"))

    # 6. pre-reform of suffix/phonetic variants (compound)
    seen_forms = {v.form.lower() for v in vs.variants}
    for v in list(vs.variants):
        nr = _fold_prereform(v.form)
        if nr.lower() not in seen_forms:
            seen_forms.add(nr.lower())
            vs.variants.append(Variant(nr, f"pre-reform of ({v.derivation})", "candidate"))
        ny = _fold_yo(v.form)
        if ny.lower() not in seen_forms:
            seen_forms.add(ny.lower())
            vs.variants.append(Variant(ny, f"ё-fold of ({v.derivation})", "candidate"))

    # 7. OCR candidates: edit-distance against the variant dictionary
    if include_ocr and variant_dict:
        for known in variant_dict:
            if _levenshtein(core.lower(), known.lower()) <= 2 and known.lower() not in seen_forms:
                seen_forms.add(known.lower())
                vs.variants.append(Variant(known, f"OCR candidate (edit-distance ≤2 from dict)", "candidate"))

    return vs


def _levenshtein(a: str, b: str) -> int:
    """Standard Levenshtein distance."""
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (ca != cb)))
        prev = cur
    return prev[-1]


def forms_for_search(name: str, variant_dict: list[str] | None = None) -> list[str]:
    """Convenience: return just the de-duplicated forms list, ranked by confidence."""
    vs = expand_variants(name, include_ocr=bool(variant_dict), variant_dict=variant_dict)
    # rank: exact first, then likely, then candidate
    ranked = (
        [v.form for v in vs.variants if v.confidence == "exact"] +
        [v.form for v in vs.variants if v.confidence == "likely"] +
        [v.form for v in vs.variants if v.confidence == "candidate"]
    )
    seen = set()
    out = []
    for f in ranked:
        if f.lower() not in seen:
            seen.add(f.lower())
            out.append(f)
    return out
