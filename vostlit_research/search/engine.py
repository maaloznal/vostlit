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
    """Return (sql_fragment, params) for the documents-level filters."""
    if f is None:
        return ("", [])
    clauses: list[str] = []
    params: list[Any] = []
    if f.region:
        clauses.append("d.region LIKE ?")
        params.append(f"%{f.region}%")
    if f.author:
        clauses.append("LOWER(d.author) LIKE LOWER(?)")
        params.append(f"%{f.author}%")
    if f.source_type:
        clauses.append("d.source_type = ?")
        params.append(f.source_type)
    if f.date_from:
        clauses.append("COALESCE(d.publication_year, d.original_creation_date, '') >= ?")
        params.append(f.date_from)
    if f.date_to:
        clauses.append("COALESCE(d.publication_year, d.original_creation_date, '') <= ?")
        params.append(f.date_to)
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
    """Return the set of document ids allowed by filters, or None = all."""
    if f is None:
        return None
    where, params = _filters_where(f)
    sql = f"SELECT d.id FROM documents d {where}"
    rows = db.conn.execute(sql, params).fetchall()
    return {r["id"] for r in rows} if rows else set()


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
        # also FTS
        fts_rows = _fts.fts_match_name_variants(self.db.conn, name, limit=limit)
        seen = {r["id"] for r in rows}
        for fr in fts_rows:
            if fr["variant_id"] in seen:
                continue
            v = self.db.conn.execute(
                "SELECT id, entity_id, original_form, normalized_form, language, variant_type, verification_status, evidence_section_id FROM name_variants WHERE id = ?",
                (fr["variant_id"],),
            ).fetchone()
            if v:
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
        """
        if not name:
            return []
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
