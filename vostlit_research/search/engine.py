"""The unified search engine.

Strategies (all return :class:`SearchResult` lists):

  * ``search_exact``     — phrase match on original text (case-insensitive,
                           Cyrillic-aware, ё preserved). SQL LIKE on the
                           ``text_lower`` column.
  * ``search``           — FTS5 ranked full-text over normalised sections.
  * ``search_variants``  — name-variant dictionary lookup (exact original,
                           exact normalised, FTS on forms).
  * ``search_fuzzy``     — difflib similarity over name_variants + entity
                           canonical names. Results are CANDIDATES only.
  * ``search_context``   — exact phrase + co-occurrence filters (region,
                           author, date, source_type).
  * ``search_hybrid``    — combine the above with explainable ranking.

Snippet extraction is token-based so it returns ORIGINAL orthography with
correct character offsets (see _locate_and_snippet).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .. import textnorm
from ..db import Database
from . import fts as _fts
from .semantic import get_semantic_provider

_WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass
class SearchFilters:
    region: str | None = None
    author: str | None = None
    source_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    page_types: tuple[str, ...] | None = None
    document_ids: tuple[int, ...] | None = None


@dataclass
class SearchResult:
    document_id: int
    canonical_url: str
    title: str | None
    author: str | None
    region: str | None
    publication_year: str | None
    section_id: int | None
    section_type: str | None
    match_type: str              # exact|fts|variant|fuzzy|semantic|hybrid
    snippet: str | None
    context_before: str | None
    context_after: str | None
    score: float
    explanation: str
    confidence: str = "probable"  # verified|probable|possible|candidate

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------- helpers

def _doc_row(db: Database, document_id: int) -> Any:
    return db.conn.execute(
        "SELECT id, canonical_url, title, author, region, publication_year, page_type FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()


def _filters_where(f: SearchFilters | None) -> tuple[str, list[Any]]:
    """Return (sql_fragment, params) for the documents-level filters.

    F2 fix: region/author filters are now Cyrillic-case-insensitive by
    folding both sides through ``lower_cyr`` (SQLite's LOWER() is ASCII-only).
    F3 fix: date filters prefer ``original_creation_date`` (the date the
    SOURCE describes) over ``publication_year`` (the edition's date), and
    compare numerically via CAST(substr(...,1,4) AS INTEGER) instead of
    lexicographically.
    """
    if f is None:
        return ("", [])
    clauses: list[str] = []
    params: list[Any] = []
    # F2: region/author are matched in Python (_allowed_doc_ids) because
    # SQLite's LOWER() is ASCII-only and would miss Cyrillic case.
    if f.source_type:
        clauses.append("d.source_type = ?")
        params.append(f.source_type)
    if f.date_from or f.date_to:
        # F3: prefer original_creation_date (the event date) over publication_year.
        # Compare numerically on the first 4 chars (year), ignoring non-numeric.
        # If original_creation_date is NULL, fall back to publication_year.
        if f.date_from:
            clauses.append(
                "CAST(substr(COALESCE(d.original_creation_date, d.publication_year, '9999'),1,4) AS INTEGER) >= ?"
            )
            params.append(int(f.date_from))
        if f.date_to:
            clauses.append(
                "CAST(substr(COALESCE(d.original_creation_date, d.publication_year, '0000'),1,4) AS INTEGER) <= ?"
            )
            params.append(int(f.date_to))
    if f.page_types:
        placeholders = ",".join("?" for _ in f.page_types)
        clauses.append(f"d.page_type IN ({placeholders})")
        params.extend(f.page_types)
    if f.document_ids:
        placeholders = ",".join("?" for _ in f.document_ids)
        clauses.append(f"d.id IN ({placeholders})")
        params.extend(f.document_ids)
    if not clauses:
        return ("", [])
    return ("WHERE " + " AND ".join(clauses), params)


def _allowed_doc_ids(db: Database, f: SearchFilters | None) -> set[int] | None:
    """Return the set of document ids allowed by filters, or None = all.

    F2 fix: region/author matching is done in Python with ``fold_for_match``
    (Cyrillic-aware, ё/pre-reform-insensitive) because SQLite's LOWER() is
    ASCII-only and would miss 'дагестан' vs 'Дагестан'.
    """
    if f is None:
        return None
    where, params = _filters_where(f)
    sql = f"SELECT d.id, d.region, d.author, d.source_type, d.page_type, d.original_creation_date, d.publication_year FROM documents d {where}"
    rows = db.conn.execute(sql, params).fetchall()
    if not rows:
        return set()
    if f.region is None and f.author is None:
        return {r["id"] for r in rows}
    # F2: Python-side Cyrillic-aware region/author matching
    region_q = textnorm.fold_for_match(f.region) if f.region else None
    author_q = textnorm.fold_for_match(f.author) if f.author else None
    out: set[int] = set()
    for r in rows:
        if region_q is not None:
            if region_q not in textnorm.fold_for_match(r["region"] or ""):
                continue
        if author_q is not None:
            if author_q not in textnorm.fold_for_match(r["author"] or ""):
                continue
        out.add(r["id"])
    return out


def _tokenize_with_offsets(text: str) -> list[tuple[str, int, int]]:
    """Return [(normalised_token, start, end), ...] over the ORIGINAL text."""
    out = []
    for m in _WORD_RE.finditer(text or ""):
        tok = textnorm.normalise_search(m.group(0))
        if tok:
            out.append((tok, m.start(), m.end()))
    return out


def _locate_and_snippet(
    original: str, query: str, *, width: int = 120
) -> tuple[str | None, str | None, str | None]:
    """Find the first occurrence of ``query`` in ``original`` and return
    (snippet, context_before, context_after) using ORIGINAL characters.

    Matching is a SUBSTRING search on a 1:1 character fold (fold_for_match:
    NFKC + pre-reform + ё + lower, offset-preserving). This finds inflected
    forms (e.g. query "Дагестан" matches "дагестанских") while keeping the
    snippet in the original orthography with correct offsets. ъ/ъ-less
    mismatches are not handled here (rare; the token-level normalise_search
    used by FTS covers them).
    """
    if not original or not query:
        return None, None, None
    folded_orig = textnorm.fold_for_match(original)
    folded_q = textnorm.fold_for_match(query)
    if not folded_q:
        return None, None, None
    idx = folded_orig.find(folded_q)
    if idx < 0:
        # fall back to a normalised substring (drops ъ; may shift offsets but
        # still returns a useful window around the match)
        norig = textnorm.normalise_search(original)
        nq = textnorm.normalise_search(query)
        if not nq:
            return None, None, None
        j = norig.find(nq)
        if j < 0:
            return None, None, None
        # best-effort: return a window from the normalised text
        pre = norig[max(0, j - width):j]
        post = norig[j + len(nq):j + len(nq) + width]
        snip = norig[max(0, j - width // 2):j + len(nq) + width // 2]
        return snip.strip(), pre.strip(), post.strip()
    end = idx + len(folded_q)
    pre = original[max(0, idx - width):idx]
    post = original[end:end + width]
    snip = original[max(0, idx - width // 2):min(len(original), end + width // 2)]
    return snip.strip(), pre.strip(), post.strip()


# ---------------------------------------------------------------------- engine

class SearchEngine:
    def __init__(self, db: Database):
        self.db = db
        self._semantic = get_semantic_provider(db)

    # --- exact ------------------------------------------------------------
    def search_exact(self, phrase: str, filters: SearchFilters | None = None, *, limit: int = 50) -> list[SearchResult]:
        """Exact phrase search on ORIGINAL text (Cyrillic-aware CI)."""
        if not phrase:
            return []
        allowed = _allowed_doc_ids(self.db, filters)
        needle = textnorm.lower_cyr(phrase)
        results: list[SearchResult] = []
        # scan sections; filter by allowed doc set
        sql = "SELECT id, document_id, section_type, text, text_lower FROM document_sections WHERE text_lower LIKE ?"
        rows = self.db.conn.execute(sql, (f"%{needle}%",)).fetchall()
        for r in rows:
            if allowed is not None and r["document_id"] not in allowed:
                continue
            snip, pre, post = _locate_and_snippet(r["text"] or "", phrase, width=140)
            doc = _doc_row(self.db, r["document_id"])
            results.append(SearchResult(
                document_id=r["document_id"],
                canonical_url=doc["canonical_url"] if doc else None,
                title=doc["title"] if doc else None,
                author=doc["author"] if doc else None,
                region=doc["region"] if doc else None,
                publication_year=doc["publication_year"] if doc else None,
                section_id=r["id"],
                section_type=r["section_type"],
                match_type="exact",
                snippet=snip,
                context_before=pre,
                context_after=post,
                score=1.0,
                explanation=f"exact phrase match in section #{r['id']} ({r['section_type']})",
                confidence="verified",
            ))
            if len(results) >= limit:
                break
        return results

    # --- full-text --------------------------------------------------------
    def search(self, query: str, filters: SearchFilters | None = None, *, limit: int = 50) -> list[SearchResult]:
        """FTS5 ranked full-text search over normalised sections."""
        if not query:
            return []
        allowed = _allowed_doc_ids(self.db, filters)
        rows = _fts.fts_match_sections(self.db.conn, query, limit=limit * 3)
        results: list[SearchResult] = []
        for r in rows:
            if allowed is not None and r["document_id"] not in allowed:
                continue
            sec = self.db.conn.execute(
                "SELECT id, section_type, text, heading FROM document_sections WHERE id = ?",
                (r["section_id"],),
            ).fetchone()
            if sec is None:
                continue
            doc = _doc_row(self.db, r["document_id"])
            snip, pre, post = _locate_and_snippet(sec["text"] or "", query, width=140)
            results.append(SearchResult(
                document_id=r["document_id"],
                canonical_url=doc["canonical_url"] if doc else None,
                title=doc["title"] if doc else None,
                author=doc["author"] if doc else None,
                region=doc["region"] if doc else None,
                publication_year=doc["publication_year"] if doc else None,
                section_id=r["section_id"],
                section_type=sec["section_type"],
                match_type="fts",
                snippet=snip,
                context_before=pre,
                context_after=post,
                score=float(r["score"]),
                explanation=f"full-text match (bm25={r['score']:.3f})",
                confidence="probable",
            ))
            if len(results) >= limit:
                break
        return results

    # --- name variants ----------------------------------------------------
    def search_variants(self, name: str, filters: SearchFilters | None = None, *, limit: int = 50) -> list[SearchResult]:
        """Look up the name-variant dictionary.

        Returns variants matching the original or normalised form, plus their
        owning entities and (if linked) the evidence section. Each result's
        ``snippet`` is the original_form (so the agent sees the exact spelling).

        F1 fix: filters are now applied — variants whose evidence_section_id
        points at a section in a non-matching document are filtered out, and
        the entity's canonical name is checked against the region/author filter
        via its evidence document.
        """
        if not name:
            return []
        norm = textnorm.normalise_search(name)
        rows = self.db.conn.execute(
            """SELECT v.id, v.entity_id, v.original_form, v.normalized_form,
                      v.language, v.variant_type, v.verification_status,
                      v.evidence_section_id, e.canonical_name, e.entity_type, e.description
               FROM name_variants v LEFT JOIN entities e ON e.id = v.entity_id
               WHERE v.normalized_form = ? OR v.original_form = ? OR v.normalized_form LIKE ?
               LIMIT ?""",
            (norm, name, f"%{norm}%", limit),
        ).fetchall()
        # F1: apply filters — if the variant has an evidence_section_id, check
        # its document against the filter; if it has none, keep it (dictionary
        # entry, not yet attested).
        allowed = _allowed_doc_ids(self.db, filters)
        if allowed is not None:
            kept = []
            for r in rows:
                if r["evidence_section_id"] is None:
                    kept.append(r)  # dictionary-only variant; keep
                    continue
                s = self.db.conn.execute(
                    "SELECT document_id FROM document_sections WHERE id = ?",
                    (r["evidence_section_id"],)
                ).fetchone()
                if s and s["document_id"] in allowed:
                    kept.append(r)
            rows = kept
        # also FTS — but apply the SAME F1 filter to FTS hits
        fts_rows = _fts.fts_match_name_variants(self.db.conn, name, limit=limit)
        seen = {r["id"] for r in rows}
        for fr in fts_rows:
            if fr["variant_id"] in seen:
                continue
            v = self.db.conn.execute(
                "SELECT id, entity_id, original_form, normalized_form, language, variant_type, verification_status, evidence_section_id FROM name_variants WHERE id = ?",
                (fr["variant_id"],),
            ).fetchone()
            if v is None:
                continue
            # F1: apply the same evidence-document filter to FTS hits
            if allowed is not None and v["evidence_section_id"] is not None:
                s = self.db.conn.execute(
                    "SELECT document_id FROM document_sections WHERE id = ?",
                    (v["evidence_section_id"],)
                ).fetchone()
                if not (s and s["document_id"] in allowed):
                    continue
            rows.append(v)
        results: list[SearchResult] = []
        for r in rows:
            ent_name = None
            if r["entity_id"]:
                e = self.db.conn.execute("SELECT canonical_name, entity_type, description FROM entities WHERE id = ?", (r["entity_id"],)).fetchone()
                ent_name = e["canonical_name"] if e else None
            doc_id = None
            sec_id = r["evidence_section_id"]
            if sec_id:
                s = self.db.conn.execute("SELECT document_id FROM document_sections WHERE id = ?", (sec_id,)).fetchone()
                if s:
                    doc_id = s["document_id"]
            doc = _doc_row(self.db, doc_id) if doc_id else None
            title = ent_name or (doc["title"] if doc else None)
            results.append(SearchResult(
                document_id=doc_id or 0,
                canonical_url=doc["canonical_url"] if doc else None,
                title=title,
                author=ent_name,
                region=doc["region"] if doc else None,
                publication_year=doc["publication_year"] if doc else None,
                section_id=sec_id,
                section_type="name_variant",
                match_type="variant",
                snippet=r["original_form"],
                context_before=None,
                context_after=f"normalised={r['normalized_form']}; type={r['variant_type']}; status={r['verification_status']}",
                score=1.0 if r["normalized_form"] == norm else 0.8,
                explanation=f"name variant of entity «{ent_name}» (type={r['variant_type']}, status={r['verification_status']})",
                confidence=r["verification_status"],
            ))
        return results[:limit]

    # --- fuzzy ------------------------------------------------------------
    def search_fuzzy(self, name: str, filters: SearchFilters | None = None, *, threshold: float = 0.72, limit: int = 50) -> list[SearchResult]:
        """Fuzzy similarity over name_variants + entity canonical names.

        Results are CANDIDATES only — the explanation says so explicitly.

        N2 fix: filters are now applied — variant candidates whose evidence
        is in a non-matching document are filtered out (same logic as
        search_variants). Entity candidates with no evidence are kept (they
        are dictionary-level, not corpus-attested).
        """
        if not name:
            return []
        allowed = _allowed_doc_ids(self.db, filters)
        cands: list[tuple[str, Any]] = []
        for r in self.db.conn.execute("SELECT id, original_form FROM name_variants"):
            cands.append((r["original_form"], ("variant", r["id"])))
        for r in self.db.conn.execute("SELECT id, canonical_name FROM entities"):
            cands.append((r["canonical_name"], ("entity", r["id"])))
        matches = textnorm.fuzzy_candidates(name, cands, threshold=threshold, limit=limit)
        results: list[SearchResult] = []
        for score, (kind, oid) in matches:
            if kind == "variant":
                v = self.db.conn.execute("SELECT id, entity_id, original_form, normalized_form, verification_status, evidence_section_id FROM name_variants WHERE id = ?", (oid,)).fetchone()
                # N2: apply filter to variant candidates with evidence
                if allowed is not None and v and v["evidence_section_id"] is not None:
                    s = self.db.conn.execute(
                        "SELECT document_id FROM document_sections WHERE id = ?",
                        (v["evidence_section_id"],)
                    ).fetchone()
                    if not (s and s["document_id"] in allowed):
                        continue
                ent = None
                if v and v["entity_id"]:
                    e = self.db.conn.execute("SELECT canonical_name FROM entities WHERE id = ?", (v["entity_id"],)).fetchone()
                    ent = e["canonical_name"] if e else None
                results.append(SearchResult(
                    document_id=0,
                    canonical_url=None,
                    title=ent,
                    author=ent,
                    region=None,
                    publication_year=None,
                    section_id=v["evidence_section_id"] if v else None,
                    section_type="name_variant",
                    match_type="fuzzy",
                    snippet=v["original_form"] if v else None,
                    context_before=None,
                    context_after=f"score={score:.2f}; normalised={v['normalized_form'] if v else None}",
                    score=score,
                    explanation=f"fuzzy candidate (similarity={score:.2f}) — NOT a confirmed identity",
                    confidence="candidate",
                ))
            else:
                e = self.db.conn.execute("SELECT id, canonical_name, entity_type FROM entities WHERE id = ?", (oid,)).fetchone()
                results.append(SearchResult(
                    document_id=0,
                    canonical_url=None,
                    title=e["canonical_name"] if e else None,
                    author=e["canonical_name"] if e else None,
                    region=None,
                    publication_year=None,
                    section_id=None,
                    section_type="entity",
                    match_type="fuzzy",
                    snippet=e["canonical_name"] if e else None,
                    context_before=None,
                    context_after=f"score={score:.2f}; entity_type={e['entity_type'] if e else None}",
                    score=score,
                    explanation=f"fuzzy candidate entity (similarity={score:.2f}) — NOT a confirmed identity",
                    confidence="candidate",
                ))
        return results[:limit]

    # --- context (co-occurrence) -----------------------------------------
    def search_context(self, query: str, filters: SearchFilters | None = None, *, limit: int = 50) -> list[SearchResult]:
        """Exact phrase search with the filters applied as first-class."""
        return self.search_exact(query, filters, limit=limit)

    # --- semantic (pluggable, no-op by default) ---------------------------
    def search_semantic(self, query: str, filters: SearchFilters | None = None, *, limit: int = 50) -> list[SearchResult]:
        return self._semantic.search(query, filters, limit=limit)

    # --- hybrid -----------------------------------------------------------
    def search_hybrid(self, query: str, filters: SearchFilters | None = None, *, limit: int = 50) -> list[SearchResult]:
        """Combine exact + fts + variants + fuzzy with explainable ranking.

        Ranking priority (a semantic hit never outranks a real source quote):
          1. exact phrase in source text        (verified,   +1000)
          2. name-variant dictionary match       (verified,   +500)
          3. full-text ranked match              (probable,   bm25 normalised)
          4. fuzzy candidate                     (candidate,  similarity)
        """
        by_key: dict[tuple, SearchResult] = {}
        bucket: list[tuple[float, SearchResult]] = []

        for r in self.search_exact(query, filters, limit=limit * 2):
            bucket.append((1000.0 + r.score, r))
        for r in self.search_variants(query, filters, limit=limit * 2):
            bucket.append((500.0 + r.score, r))
        for r in self.search(query, filters, limit=limit * 2):
            # normalise bm25 (negative, more-negative = better) to a 0..1 bonus
            bonus = 0.0
            bucket.append((10.0 + bonus + (1.0 / (1.0 + abs(r.score))), r))
        for r in self.search_fuzzy(query, filters, limit=limit * 2):
            bucket.append((1.0 + r.score, r))
        # semantic (no-op unless a provider is configured)
        for r in self.search_semantic(query, filters, limit=limit):
            bucket.append((0.5, r))

        # de-dup by (document_id, section_id, match_type) keeping the best score
        for score, r in bucket:
            key = (r.document_id, r.section_id, r.match_type)
            if key not in by_key or score > by_key[key].score:
                r2 = SearchResult(**{**r.to_dict(), "match_type": "hybrid", "score": round(score, 4)})
                by_key[key] = r2
        ordered = sorted(by_key.values(), key=lambda x: x.score, reverse=True)
        return ordered[:limit]

    # --- toponym candidate table (master prompt §11) ---------------------
    def search_toponym(self, name: str, filters: "SearchFilters | None" = None, *,
                       limit: int = 50) -> dict:
        """Run the full toponym-search algorithm and return a candidate table.

        Implements the §11 pipeline:
          1. strip generic geographic terms (гора/хребет/перевал/урочище/меер/...)
             to get the toponym CORE; keep both forms.
          2. search exact + fts for the full form AND the core.
          3. look up the name-variant dictionary for both forms.
          4. fuzzy-match against variants + entities (candidates only).
          5. assemble a de-duplicated candidate table with, per candidate:
             form_searched, match_type, document_id, section_id, snippet,
             context, confidence, argument, source_url.

        Returns a dict with the query breakdown and the candidate list. The
        verdict is NOT produced here — that is the agent's judgment (this
        method only gathers evidence, per the anti-fabrication rules).
        """
        from .. import textnorm
        core = textnorm.strip_geo_generic(name)
        forms = [name]
        if core and core != textnorm.normalise_search(name):
            forms.append(core)
        # also include the normalised full form (so we don't miss ё/pre-reform
        # variants of the user's spelling)
        norm_full = textnorm.normalise_search(name)
        if norm_full and norm_full not in [textnorm.normalise_search(f) for f in forms]:
            forms.append(norm_full)

        candidates: list[dict] = []
        seen_keys: set[tuple] = set()

        def _add(result: "SearchResult", form: str, matched_as: str) -> None:
            key = (result.document_id, result.section_id, matched_as)
            if key in seen_keys:
                return
            seen_keys.add(key)
            doc = _doc_row(self.db, result.document_id) if result.document_id else None
            candidates.append({
                "form_searched": form,
                "matched_as": matched_as,
                "document_id": result.document_id,
                "section_id": result.section_id,
                "title": result.title,
                "author": result.author,
                "region": result.region or (doc["region"] if doc else None),
                "publication_year": result.publication_year,
                "source_url": result.canonical_url,
                "snippet": result.snippet,
                "context_before": result.context_before,
                "context_after": result.context_after,
                "confidence": result.confidence,
                "argument": result.explanation,
            })

        for form in forms:
            for r in self.search_exact(form, filters, limit=limit):
                _add(r, form, "exact")
            for r in self.search(form, filters, limit=limit):
                _add(r, form, "fts")
            for r in self.search_variants(form, limit=limit):
                _add(r, form, "variant")
        for r in self.search_fuzzy(core or name, filters, limit=limit):
            _add(r, core or name, "fuzzy_candidate")

        # rank: exact > variant > fts > fuzzy
        rank = {"exact": 0, "variant": 1, "fts": 2, "fuzzy_candidate": 3}
        candidates.sort(key=lambda c: (rank.get(c["matched_as"], 9), -len(c.get("snippet") or "")))

        return {
            "query": name,
            "core_toponym": core,
            "forms_searched": forms,
            "n_candidates": len(candidates),
            "candidates": candidates[:limit],
            "note": "candidates only — do not infer identity without context + date + geography corroboration",
        }
