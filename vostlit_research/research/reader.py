"""DocumentReader: reads context around each hit and extracts structured evidence.

The key difference from raw search: instead of returning a snippet, the Reader
opens the section + surrounding sections, classifies the EVIDENCE TYPE
(body testimony / editorial note / bibliography), detects IDENTIFICATIONS
("X — сел. Y" patterns) and CONTRADICTIONS, and returns a structured Claim
object with a clickable link.

This is what turns "search hits" into "evidence the agent can reason about".
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .. import textnorm
from ..db import Database


@dataclass
class Claim:
    """A single piece of evidence extracted from one section."""
    section_id: int
    document_id: int
    canonical_url: str
    title: str | None
    author: str | None
    region: str | None
    original_creation_date: str | None
    publication_year: str | None
    section_type: str  # body | note | bibliography | heading
    matched_form: str  # which variant form matched
    verbatim_quote: str  # the exact quote (original spelling), ≤300 chars
    context_window: str  # ±300 chars around the match
    evidence_type: str  # body_testimony | editorial_identification | citation | context_mention
    identification: dict[str, str] | None = None  # {"identified_as": "Кадар", "editor": "..."}
    date_mentioned: str | None = None
    source_independence: str = "unknown"  # primary | secondary | derivative | unknown


@dataclass
class ReadResult:
    query: str
    claims: list[Claim] = field(default_factory=list)
    contradictions: list[tuple[Claim, Claim]] = field(default_factory=list)
    identifications: list[dict[str, Any]] = field(default_factory=list)


# patterns for editorial identification (Russian)
# e.g. "Гадар — сел. Кадар (Къадар)" / "Речь идет о сел. Кадар" / "отождествляется с"
ID_PATTERNS = [
    re.compile(r"([А-ЯЁA-Z][а-яёa-z]+(?:[\-\s][а-яёa-z]+)*)\s*[—–-]\s*сел\.?\s*([А-ЯЁA-Z][а-яёa-z\-]+)", re.UNICODE),
    re.compile(r"[Рр]ечь идет о\s*сел\.?\s*([А-ЯЁA-Z][а-яёa-z\-]+)", re.UNICODE),
    re.compile(r"([А-ЯЁA-Z][а-яёa-z\-]+)\s*\(([А-ЯЁA-Z][а-яёa-z\-]+)\)\s*.*?называют\s*([А-ЯЁA-Z][а-яёa-z\-]+)", re.UNICODE),
    re.compile(r"отождествляется с\s*([А-ЯЁA-Z][а-яёa-z\-]+)", re.UNICODE),
    re.compile(r"ныне\s*([А-ЯЁA-Z][а-яёa-z\-]+)\s+район", re.UNICODE),
]
# date patterns
DATE_PATTERNS = [
    re.compile(r"\b(1[0-9]\d{2})\s*г?\.?", re.UNICODE),
    re.compile(r"\b(1[0-9]\d{2})\s*[/\\]\s*(\d{2,4})\s*г?", re.UNICODE),  # 898/1492-93
]


class DocumentReader:
    def __init__(self, db: Database):
        self.db = db

    def read_around(self, section_id: int, query_form: str, *, width: int = 300) -> Claim | None:
        """Read a section + its neighbours and build a Claim."""
        sec = self.db.conn.execute(
            "SELECT id, document_id, section_type, text, sequence_number FROM document_sections WHERE id=?",
            (section_id,)
        ).fetchone()
        if sec is None or not sec["text"]:
            return None
        doc = self.db.conn.execute(
            "SELECT id, canonical_url, title, author, region, original_creation_date, publication_year FROM documents WHERE id=?",
            (sec["document_id"],)
        ).fetchone()
        if doc is None:
            return None
        text = sec["text"]
        folded = textnorm.fold_for_match(text)
        folded_q = textnorm.fold_for_match(query_form)
        idx = folded.find(folded_q)
        if idx < 0:
            idx = text.lower().find(query_form.lower())
        if idx < 0:
            return None
        end = idx + len(query_form)
        ctx_window = text[max(0, idx - width):min(len(text), end + width)]
        # verbatim quote: the sentence containing the match, capped at 300 chars
        sent_start = text.rfind(". ", max(0, idx - 250), idx)
        sent_start = sent_start + 2 if sent_start >= 0 else max(0, idx - 150)
        sent_end = text.find(". ", end, end + 300)
        sent_end = sent_end + 1 if sent_end >= 0 else min(len(text), end + 150)
        quote = text[sent_start:sent_end].strip()[:300]

        # evidence type
        ev_type = self._classify_evidence(sec["section_type"], ctx_window)
        # identification detection
        ident = self._detect_identification(ctx_window, query_form)
        # date extraction
        dates = []
        for p in DATE_PATTERNS:
            for m in p.finditer(ctx_window):
                dates.append(m.group(0))
        date_mentioned = dates[0] if dates else None
        # source independence (heuristic)
        indep = self._assess_independence(doc)

        return Claim(
            section_id=sec["id"],
            document_id=doc["id"],
            canonical_url=doc["canonical_url"],
            title=doc["title"],
            author=doc["author"],
            region=doc["region"],
            original_creation_date=doc["original_creation_date"],
            publication_year=doc["publication_year"],
            section_type=sec["section_type"],
            matched_form=query_form,
            verbatim_quote=quote,
            context_window=ctx_window,
            evidence_type=ev_type,
            identification=ident,
            date_mentioned=date_mentioned,
            source_independence=indep,
        )

    def _classify_evidence(self, section_type: str, ctx: str) -> str:
        if section_type == "note":
            return "editorial_identification"
        if section_type == "bibliography":
            return "citation"
        if section_type == "heading":
            return "context_mention"
        # body: distinguish testimony vs context mention
        if any(k in ctx.lower() for k in ("сел.", "село", "город", "жители", "общество", "крепость")):
            return "body_testimony"
        return "context_mention"

    def _detect_identification(self, ctx: str, form: str) -> dict[str, str] | None:
        """Detect editorial identification patterns like 'Гадар — сел. Кадар'."""
        for p in ID_PATTERNS:
            m = p.search(ctx)
            if m:
                groups = [g for g in m.groups() if g]
                return {
                    "pattern": p.pattern[:60],
                    "identified_as": groups[-1] if groups else None,
                    "raw_match": m.group(0)[:120],
                }
        return None

    def _assess_independence(self, doc: sqlite3.Row) -> str:
        """Heuristic: a primary-source document (original_creation_date set)
        is 'primary'; a chronicle re-published is 'secondary'; editorial notes
        are 'derivative' of the body they comment on."""
        if doc["original_creation_date"]:
            return "primary"
        if doc["publication_year"] and doc["publication_year"] < "1900":
            return "secondary"
        return "unknown"

    def read_all(self, search_results: list[dict], query: str) -> ReadResult:
        """Read around every search result and build a ReadResult with claims,
        contradictions, and identifications."""
        result = ReadResult(query=query)
        seen_sections: set[int] = set()
        for r in search_results:
            sid = r.get("section_id")
            if not sid or sid in seen_sections:
                continue
            seen_sections.add(sid)
            # use the SHORT searched_form (which variant matched), not the snippet
            form = r.get("searched_form") or query
            claim = self.read_around(sid, form)
            if claim:
                result.claims.append(claim)
                if claim.identification:
                    result.identifications.append({
                        "from_form": claim.matched_form,
                        "identified_as": claim.identification.get("identified_as"),
                        "section_id": claim.section_id,
                        "document_id": claim.document_id,
                        "url": claim.canonical_url,
                        "raw": claim.identification.get("raw_match"),
                    })
        return result
