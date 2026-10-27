"""High-level research tools (master prompt §9).

These wrap :class:`SearchEngine` and the DB to give the agent a small, stable
API. Every result keeps a verifiable link to a source document + section.
"""

from __future__ import annotations

import json
from typing import Any

from ..db import Database
from ..search.engine import SearchEngine, SearchFilters, SearchResult


class ResearchEngine:
    def __init__(self, db: Database):
        self.db = db
        self.search_engine = SearchEngine(db)

    # --- lookups ----------------------------------------------------------
    def get_document(self, document_id: int) -> dict[str, Any] | None:
        doc = self.db.conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if doc is None:
            return None
        d = dict(doc)
        ver = None
        if doc["current_version_id"]:
            ver = self.db.conn.execute(
                "SELECT extracted_text, extraction_method, extracted_at, content_hash, parser_version, extraction_warnings FROM document_versions WHERE id = ?",
                (doc["current_version_id"],),
            ).fetchone()
        if ver:
            d["extracted_text"] = ver["extracted_text"]
            d["extraction_method"] = ver["extraction_method"]
            d["extracted_at"] = ver["extracted_at"]
            d["content_hash"] = ver["content_hash"]
            d["parser_version"] = ver["parser_version"]
            d["extraction_warnings"] = json.loads(ver["extraction_warnings"]) if ver["extraction_warnings"] else []
        return d

    def get_document_by_url(self, url: str) -> dict[str, Any] | None:
        from .. import textnorm
        row = self.db.conn.execute(
            "SELECT id FROM documents WHERE canonical_url = ?", (textnorm.normalise_url(url),)
        ).fetchone()
        return self.get_document(int(row["id"])) if row else None

    def get_section(self, section_id: int) -> dict[str, Any] | None:
        s = self.db.conn.execute("SELECT * FROM document_sections WHERE id = ?", (section_id,)).fetchone()
        return dict(s) if s else None

    def get_context(self, section_id: int, before: int = 1, after: int = 1) -> dict[str, Any]:
        """Return the section plus ``before``/``after`` sibling sections by sequence."""
        s = self.db.conn.execute(
            "SELECT * FROM document_sections WHERE id = ?", (section_id,)
        ).fetchone()
        if s is None:
            return {"error": f"section {section_id} not found"}
        doc_id = s["document_id"]
        seq = s["sequence_number"]
        pre = self.db.conn.execute(
            "SELECT * FROM document_sections WHERE document_id = ? AND sequence_number < ? ORDER BY sequence_number DESC LIMIT ?",
            (doc_id, seq, before),
        ).fetchall()
        post = self.db.conn.execute(
            "SELECT * FROM document_sections WHERE document_id = ? AND sequence_number > ? ORDER BY sequence_number ASC LIMIT ?",
            (doc_id, seq, after),
        ).fetchall()
        return {
            "section": dict(s),
            "before": [dict(r) for r in reversed(pre)],
            "after": [dict(r) for r in post],
        }

    def get_document_bibliography(self, document_id: int) -> dict[str, Any]:
        doc = self.db.conn.execute("SELECT bibliography, publication_title FROM documents WHERE id = ?", (document_id,)).fetchone()
        if doc is None:
            return {"error": f"document {document_id} not found"}
        bib_sections = self.db.conn.execute(
            "SELECT id, text FROM document_sections WHERE document_id = ? AND section_type = 'bibliography' ORDER BY sequence_number",
            (document_id,),
        ).fetchall()
        return {
            "bibliography": doc["bibliography"],
            "publication_title": doc["publication_title"],
            "bibliography_sections": [dict(r) for r in bib_sections],
        }

    # --- searches ---------------------------------------------------------
    def _filters(self, **kw: Any) -> SearchFilters | None:
        if not kw:
            return None
        return SearchFilters(**kw)

    def search_documents(self, query: str, *, limit: int = 50, **filters: Any) -> list[dict]:
        return [r.to_dict() for r in self.search_engine.search_hybrid(query, self._filters(**filters), limit=limit)]

    def search_exact(self, phrase: str, *, limit: int = 50, **filters: Any) -> list[dict]:
        return [r.to_dict() for r in self.search_engine.search_exact(phrase, self._filters(**filters), limit=limit)]

    def search_name_variants(self, name: str, *, limit: int = 50) -> list[dict]:
        return [r.to_dict() for r in self.search_engine.search_variants(name, limit=limit)]

    def search_fuzzy(self, name: str, *, threshold: float = 0.72, limit: int = 50) -> list[dict]:
        return [r.to_dict() for r in self.search_engine.search_fuzzy(name, threshold=threshold, limit=limit)]

    def search_by_region(self, region: str, query: str | None = None, *, limit: int = 50) -> list[dict]:
        f = self._filters(region=region)
        if query:
            return [r.to_dict() for r in self.search_engine.search_hybrid(query, f, limit=limit)]
        # no query: list documents in region
        rows = self.db.conn.execute(
            "SELECT id, canonical_url, title, author, region, publication_year, page_type FROM documents WHERE region LIKE ? ORDER BY title LIMIT ?",
            (f"%{region}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_by_author(self, author: str, query: str | None = None, *, limit: int = 50) -> list[dict]:
        f = self._filters(author=author)
        if query:
            return [r.to_dict() for r in self.search_engine.search_hybrid(query, f, limit=limit)]
        rows = self.db.conn.execute(
            "SELECT id, canonical_url, title, author, region, publication_year FROM documents WHERE author LIKE ? ORDER BY title LIMIT ?",
            (f"%{author}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_by_date(self, date_from: str | None, date_to: str | None, query: str | None = None, *, limit: int = 50) -> list[dict]:
        f = self._filters(date_from=date_from, date_to=date_to)
        if query:
            return [r.to_dict() for r in self.search_engine.search_hybrid(query, f, limit=limit)]
        rows = self.db.conn.execute(
            "SELECT id, canonical_url, title, author, publication_year FROM documents WHERE COALESCE(publication_year, original_creation_date, '') BETWEEN COALESCE(?, '') AND COALESCE(?, 'zzz') ORDER BY publication_year LIMIT ?",
            (date_from, date_to, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- mentions / comparison -------------------------------------------
    def find_mentions(self, name: str, *, limit: int = 50) -> list[dict]:
        """Find mentions of a name across the corpus.

        Combines the mentions table with exact-text search, so it works even
        before any entity/mention has been manually curated.
        """
        out: list[dict] = []
        # 1. curated mentions
        from .. import textnorm
        norm = textnorm.normalise_search(name)
        rows = self.db.conn.execute(
            """SELECT m.id, m.entity_id, m.document_id, m.section_id, m.mention_text,
                      m.context_before, m.context_after, m.verification_status,
                      e.canonical_name, e.entity_type
               FROM mentions m LEFT JOIN entities e ON e.id = m.entity_id
               WHERE LOWER(m.mention_text) LIKE LOWER(?) LIMIT ?""",
            (f"%{name}%", limit),
        ).fetchall()
        for r in rows:
            out.append(dict(r))
        # 2. text-search fallback (marks extraction_method='text_search')
        for r in self.search_engine.search_exact(name, limit=limit):
            out.append({
                "id": None,
                "entity_id": None,
                "document_id": r.document_id,
                "section_id": r.section_id,
                "mention_text": name,
                "context_before": r.context_before,
                "context_after": r.context_after,
                "verification_status": "candidate",
                "canonical_name": None,
                "entity_type": None,
                "extraction_method": "text_search",
                "snippet": r.snippet,
            })
        return out[:limit]

    def compare_sources(self, claim: str, source_ids: list[int]) -> dict[str, Any]:
        """Gather, per source, the fragments that support or contradict a claim.

        This does NOT adjudicate — it presents the evidence so the agent (or a
        human) can. The claim is searched as a phrase in each source.
        """
        per_source: list[dict] = []
        for sid in source_ids:
            doc = self.get_document(sid)
            if not doc:
                per_source.append({"source_id": sid, "error": "not found"})
                continue
            f = SearchFilters(document_ids=(sid,))
            hits = self.search_engine.search_exact(claim, f, limit=20)
            per_source.append({
                "source_id": sid,
                "title": doc.get("title"),
                "author": doc.get("author"),
                "canonical_url": doc.get("canonical_url"),
                "matching_fragments": [r.to_dict() for r in hits],
                "n_matches": len(hits),
            })
        return {"claim": claim, "sources": per_source}

    def export_search_results(self, results: list[dict], fmt: str = "jsonl") -> str:
        if fmt == "json":
            return json.dumps(results, ensure_ascii=False, indent=2)
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in results)
