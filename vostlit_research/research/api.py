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
        # N1 fix: Cyrillic-aware region matching via fold_for_match (SQLite
        # LOWER() is ASCII-only and would miss 'дагестан' vs 'Дагестан').
        from .. import textnorm
        q = textnorm.fold_for_match(region)
        rows = self.db.conn.execute(
            "SELECT id, canonical_url, title, author, region, publication_year, page_type FROM documents ORDER BY title"
        ).fetchall()
        out = [dict(r) for r in rows if q in textnorm.fold_for_match(r["region"] or "")]
        return out[:limit]

    def search_by_author(self, author: str, query: str | None = None, *, limit: int = 50) -> list[dict]:
        f = self._filters(author=author)
        if query:
            return [r.to_dict() for r in self.search_engine.search_hybrid(query, f, limit=limit)]
        # N1 fix: Cyrillic-aware author matching
        from .. import textnorm
        q = textnorm.fold_for_match(author)
        rows = self.db.conn.execute(
            "SELECT id, canonical_url, title, author, region, publication_year FROM documents ORDER BY title"
        ).fetchall()
        out = [dict(r) for r in rows if q in textnorm.fold_for_match(r["author"] or "")]
        return out[:limit]

    def search_by_date(self, date_from: str | None, date_to: str | None, query: str | None = None, *, limit: int = 50) -> list[dict]:
        f = self._filters(date_from=date_from, date_to=date_to)
        if query:
            return [r.to_dict() for r in self.search_engine.search_hybrid(query, f, limit=limit)]
        # F3: prefer original_creation_date (event date) over publication_year,
        # compare numerically on the first 4 chars.
        clauses = []
        params: list = []
        if date_from:
            clauses.append("CAST(substr(COALESCE(d.original_creation_date, d.publication_year, '9999'),1,4) AS INTEGER) >= ?")
            params.append(int(date_from))
        if date_to:
            clauses.append("CAST(substr(COALESCE(d.original_creation_date, d.publication_year, '0000'),1,4) AS INTEGER) <= ?")
            params.append(int(date_to))
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.conn.execute(
            f"SELECT d.id, d.canonical_url, d.title, d.author, d.publication_year, d.original_creation_date FROM documents d {where} ORDER BY d.original_creation_date, d.publication_year LIMIT ?",
            params + [limit],
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

    def extract_mentions(self, *, entity_id: int | None = None,
                         overwrite: bool = False, limit_per_variant: int = 50) -> dict:
        """Heuristically extract mentions of name-variants from body sections.

        For each name_variant (optionally filtered to one entity), scans every
        ``body`` section for occurrences of the variant's ORIGINAL form and
        records a ``mentions`` row with:
          - extraction_method='heuristic'
          - verification_status='candidate'   (NEVER confirmed automatically)
          - context_before / context_after (±120 chars, original orthography)
          - mention_text = the exact matched span

        Idempotent: re-running with overwrite=False skips variant/section
        pairs already recorded. With overwrite=True, deletes prior heuristic
        mentions for the same variant+section and re-extracts.

        Returns a summary dict. This NEVER promotes a candidate to confirmed
        — that requires an explicit human/agent action.
        """
        from .. import textnorm
        where = "WHERE 1=1"
        params: list = []
        if entity_id is not None:
            where += " AND entity_id = ?"
            params.append(entity_id)
        variants = self.db.conn.execute(
            f"""SELECT id, entity_id, original_form, normalized_form
                FROM name_variants {where}""", params
        ).fetchall()
        if not variants:
            return {"variants_scanned": 0, "mentions_inserted": 0, "mentions_skipped": 0,
                    "note": "no name_variants in the dictionary; curate entities first"}

        inserted = 0
        skipped = 0
        WIDTH = 120
        for v in variants:
            vid, eid, orig, norm = v["id"], v["entity_id"], v["original_form"], v["normalized_form"]
            if not orig:
                continue
            # search in body sections using the original form (case-insensitive,
            # but ORIGINAL spelling — no folding, so pre-reform forms match only
            # themselves, which is exactly what we want for a candidate mention).
            needle = orig.lower()
            rows = self.db.conn.execute(
                """SELECT s.id, s.document_id, s.text, s.text_lower
                   FROM document_sections s
                   WHERE s.section_type = 'body' AND s.text_lower LIKE ?
                   LIMIT ?""",
                (f"%{needle}%", limit_per_variant),
            ).fetchall()
            for r in rows:
                # de-dup: skip if a heuristic mention already exists for this
                # variant + section (unless overwrite)
                if not overwrite:
                    exists = self.db.conn.execute(
                        "SELECT 1 FROM mentions WHERE name_variant_id=? AND section_id=? AND extraction_method='heuristic' LIMIT 1",
                        (vid, r["id"]),
                    ).fetchone()
                    if exists:
                        skipped += 1
                        continue
                else:
                    self.db.conn.execute(
                        "DELETE FROM mentions WHERE name_variant_id=? AND section_id=? AND extraction_method='heuristic'",
                        (vid, r["id"]),
                    )
                # locate the mention and cut context using the offset-preserving fold
                text = r["text"] or ""
                folded = textnorm.fold_for_match(text)
                folded_needle = textnorm.fold_for_match(orig)
                idx = folded.find(folded_needle)
                if idx < 0:
                    # fall back to plain lower find
                    idx = text.lower().find(needle)
                    if idx < 0:
                        continue
                end = idx + len(orig)
                ctx_before = text[max(0, idx - WIDTH):idx].strip()
                ctx_after = text[end:end + WIDTH].strip()
                mention_span = text[idx:end]
                with self.db.conn:
                    self.db.conn.execute(
                        """INSERT INTO mentions
                           (entity_id, name_variant_id, document_id, section_id,
                            mention_text, context_before, context_after,
                            mention_type, extraction_method, verification_status)
                           VALUES (?,?,?,?,?,?,?, 'inferred', 'heuristic', 'candidate')""",
                        (eid, vid, r["document_id"], r["id"],
                         mention_span, ctx_before, ctx_after),
                    )
                inserted += 1
        return {
            "variants_scanned": len(variants),
            "mentions_inserted": inserted,
            "mentions_skipped": skipped,
            "note": "all inserted mentions are 'candidate' — confirm manually before citing as evidence",
        }

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

    # === Semantic Research Engine (v0.4) ================================
    def research(self, query: str, *, region: str | None = None,
                 year: str | None = None, limit: int = 30) -> dict:
        """Full semantic research pipeline: decompose → expand variants →
        retrieve → read context → link evidence → synthesize answer.

        Returns a SynthesisResult dict with verdict, findings (each with
        clickable fragment links), identifications, contradictions, and
        next steps. Every assertion traces to a verifiable vostlit.info URL.
        """
        from .variants import expand_variants
        from .reader import DocumentReader
        from .synthesis import EvidenceLinker, render_markdown
        # 1. expand variants
        # pull the variant dictionary for OCR candidates
        variant_dict = [r["original_form"] for r in self.db.conn.execute(
            "SELECT original_form FROM name_variants"
        ).fetchall()]
        vs = expand_variants(query, variant_dict=variant_dict)
        forms = vs.forms()[:40]  # cap to avoid explosion

        # 2. retrieve across all forms
        f = SearchFilters(region=region) if region else None
        all_hits: list[dict] = []
        seen_sections: set[int] = set()
        for form in forms:
            for r in self.search_engine.search_hybrid(form, f, limit=limit):
                if r.section_id and r.section_id not in seen_sections:
                    seen_sections.add(r.section_id)
                    d = r.to_dict()
                    d["searched_form"] = form  # record WHICH variant matched
                    all_hits.append(d)

        # 3. read context around each hit → structured claims
        reader = DocumentReader(self.db)
        read_result = reader.read_all(all_hits, query)

        # 4. link evidence → synthesis
        linker = EvidenceLinker(self.db)
        synthesis = linker.link(read_result)

        # 5. render
        return {
            "query": query,
            "region": region,
            "year": year,
            "variants_searched": forms,
            "n_variants": len(forms),
            "n_hits": len(all_hits),
            "verdict": synthesis.verdict,
            "summary": synthesis.summary,
            "findings": [
                {
                    "claim": f.claim,
                    "evidence_type": f.evidence_type,
                    "confidence": f.confidence,
                    "independent_witnesses": f.independent_witnesses,
                    "forms_attested": sorted(f.forms_attested),
                    "supporting_fragments": f.supporting_fragments,
                } for f in synthesis.findings
            ],
            "identifications": synthesis.identifications,
            "contradictions": synthesis.contradictions,
            "next_steps": synthesis.next_steps,
            "markdown": render_markdown(synthesis),
        }
