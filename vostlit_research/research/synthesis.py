"""EvidenceLinker + SynthesisEngine: turn claims into a linked evidence graph
and synthesize a structured answer with clickable references.

This is the capstone of the Semantic Research Engine. It takes the Claims
from DocumentReader and:
  1. Groups them by the IDENTIFIED ENTITY (using editorial identifications).
  2. Assesses INDEPENDENCE of witnesses (via document_relations + publication
     metadata — two editions of the same chronicle = ONE witness).
  3. Detects CONTRADICTIONS (different identifications of the same form).
  4. Synthesizes a structured answer where every assertion has a clickable
     link to the exact vostlit.info fragment.

Output format (returned as a dict, also renderable as markdown):
  {
    "verdict": "Подтверждено|Вероятно|Возможно|Не установлено",
    "summary": "...",
    "findings": [
      {
        "claim": "Сел. Гадари упоминается в Гумбете в 1877 г.",
        "evidence_type": "body_testimony",
        "supporting_fragments": [
          {"url": "...#sec6064", "section_id": 6064, "quote": "...", "title": "..."},
          ...
        ],
        "independent_witnesses": 3,
        "confidence": "verified"
      },
      ...
    ],
    "identifications": [...],  # editorial X = Y
    "contradictions": [...],
    "next_steps": [...]
  }
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .reader import Claim, ReadResult
from ..db import Database


@dataclass
class Finding:
    """A grouped assertion with its supporting evidence."""
    claim: str
    evidence_type: str  # body_testimony | editorial_identification | citation
    supporting_fragments: list[dict] = field(default_factory=list)
    contradicting_fragments: list[dict] = field(default_factory=list)
    independent_witnesses: int = 0
    confidence: str = "possible"  # verified | probable | possible | unestablished
    forms_attested: set[str] = field(default_factory=set)


@dataclass
class SynthesisResult:
    verdict: str
    summary: str
    findings: list[Finding] = field(default_factory=list)
    identifications: list[dict] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    all_fragments: list[dict] = field(default_factory=list)  # flat list for citation


class EvidenceLinker:
    def __init__(self, db: Database):
        self.db = db

    def link(self, read_result: ReadResult) -> SynthesisResult:
        claims = read_result.claims
        if not claims:
            return SynthesisResult(
                verdict="Не установлено",
                summary=f"По запросу «{read_result.query}» в корпусе не найдено свидетельств.",
                next_steps=self._next_steps_empty(read_result.query),
            )

        # 1. group claims by identified entity (if any identification) or by form
        groups: dict[str, list[Claim]] = defaultdict(list)
        for c in claims:
            key = c.identification.get("identified_as") if c.identification else c.matched_form
            groups[key or c.matched_form].append(c)

        # 2. build findings
        findings: list[Finding] = []
        for key, group_claims in groups.items():
            f = Finding(
                claim=self._formulate_claim(key, group_claims),
                evidence_type=group_claims[0].evidence_type,
            )
            for c in group_claims:
                frag = {
                    "url": self._section_url(c),
                    "section_id": c.section_id,
                    "document_id": c.document_id,
                    "title": c.title,
                    "author": c.author,
                    "doc_date": c.original_creation_date,
                    "pub_year": c.publication_year,
                    "section_type": c.section_type,
                    "evidence_type": c.evidence_type,
                    "matched_form": c.matched_form,
                    "quote": c.verbatim_quote,
                    "independence": c.source_independence,
                }
                f.supporting_fragments.append(frag)
                f.forms_attested.add(c.matched_form)
            f.independent_witnesses = self._count_independent(group_claims)
            f.confidence = self._assess_confidence(f)
            findings.append(f)

        # 3. identifications
        idents = []
        for c in claims:
            if c.identification:
                idents.append({
                    "from_form": c.matched_form,
                    "identified_as": c.identification.get("identified_as"),
                    "section_id": c.section_id,
                    "url": self._section_url(c),
                    "title": c.title,
                    "raw": c.identification.get("raw_match"),
                })

        # 4. contradictions: different identifications for the same form
        contradictions = []
        form_to_idents = defaultdict(list)
        for c in claims:
            if c.identification:
                form_to_idents[c.matched_form].append(c)
        for form, cs in form_to_idents.items():
            id_as = {c.identification.get("identified_as") for c in cs if c.identification}
            if len(id_as) > 1:
                contradictions.append({
                    "form": form,
                    "different_identifications": list(id_as),
                    "claims": [{"section_id": c.section_id, "url": self._section_url(c)} for c in cs],
                })

        # 5. verdict
        verified = sum(1 for f in findings if f.confidence == "verified")
        probable = sum(1 for f in findings if f.confidence == "probable")
        if verified >= 1 and any(f.independent_witnesses >= 2 for f in findings):
            verdict = "Подтверждено"
        elif verified >= 1 or probable >= 1:
            verdict = "Вероятно"
        elif findings:
            verdict = "Возможно"
        else:
            verdict = "Не установлено"

        summary = self._summarize(read_result.query, findings, idents)

        # 6. flat fragment list for citation
        all_frags = []
        for f in findings:
            all_frags.extend(f.supporting_fragments)

        return SynthesisResult(
            verdict=verdict,
            summary=summary,
            findings=findings,
            identifications=idents,
            contradictions=contradictions,
            next_steps=self._next_steps(verdict, read_result.query),
            all_fragments=all_frags,
        )

    # --- helpers ----------------------------------------------------------
    def _section_url(self, c: Claim) -> str:
        """Build a clickable URL to the section's document on vostlit.info.
        vostlit.info doesn't have per-section anchors, so we link to the
        document URL and note the section_id for in-tool navigation."""
        return c.canonical_url

    def _formulate_claim(self, key: str, claims: list[Claim]) -> str:
        forms = sorted({c.matched_form for c in claims})
        docs = sorted({c.document_id for c in claims})
        ev_types = {c.evidence_type for c in claims}
        if "editorial_identification" in ev_types:
            return f"Форма «{forms[0]}» отождествляется редактором с «{key}»"
        if "body_testimony" in ev_types:
            dates = sorted({c.original_creation_date for c in claims if c.original_creation_date})
            when = f" ({dates[0]})" if dates else ""
            return f"Топоним упомянут в тексте источника{when} под формами: {', '.join(forms)}"
        return f"Топоним засвидетельствован в {len(docs)} документ(ах) под формами: {', '.join(forms)}"

    def _count_independent(self, claims: list[Claim]) -> int:
        """Count independent witnesses: group by document, then check
        document_relations for edition/translation links."""
        doc_ids = {c.document_id for c in claims}
        if len(doc_ids) <= 1:
            return 1
        # check document_relations: merge docs that are related as
        # separate_edition/translation_of/republication
        merged: set[int] = set()
        groups: list[set[int]] = []
        for did in doc_ids:
            related = {did}
            for r in self.db.conn.execute(
                "SELECT target_doc_id FROM document_relations WHERE source_doc_id=? AND relation_type IN ('separate_edition','translation_of','republication')",
                (did,)
            ).fetchall():
                if r["target_doc_id"] in doc_ids:
                    related.add(r["target_doc_id"])
            # merge with existing groups
            placed = False
            for g in groups:
                if g & related:
                    g |= related
                    placed = True
                    break
            if not placed:
                groups.append(related)
        return len(groups)

    def _assess_confidence(self, f: Finding) -> str:
        if f.evidence_type == "editorial_identification" and f.independent_witnesses >= 1:
            return "verified"
        if f.evidence_type == "body_testimony" and f.independent_witnesses >= 2:
            return "verified"
        if f.evidence_type == "body_testimony" and f.independent_witnesses >= 1:
            return "probable"
        if f.supporting_fragments:
            return "possible"
        return "unestablished"

    def _summarize(self, query: str, findings: list[Finding], idents: list[dict]) -> str:
        if not findings:
            return f"По запросу «{query}» свидетельств не найдено."
        n_frags = sum(len(f.supporting_fragments) for f in findings)
        forms = sorted({form for f in findings for form in f.forms_attested})
        ident_str = ""
        if idents:
            id_as = sorted({i["identified_as"] for i in idents if i.get("identified_as")})
            ident_str = f" Редактор отождествляет с: {', '.join(id_as)}."
        return (f"По запросу «{query}» найдено {n_frags} фрагментов в "
                f"{len(findings)} группе(ах). Засвидетельствованы формы: {', '.join(forms)}.{ident_str}")

    def _next_steps(self, verdict: str, query: str) -> list[str]:
        steps = []
        if verdict == "Не установлено":
            steps.append("Расширьте корпус: python3 -m vostlit_research crawl --region caucasus --limit 25")
            steps.append("Повторите: python3 -m vostlit_research research " + repr(query))
        else:
            steps.append("Проверьте контекст каждого фрагмента: context <section_id> --before 2 --after 2")
            steps.append("Проверьте независимость свидетелей через document_relations")
            steps.append("Сохраните вывод: note add --claim '...' --status source_fact --supporting sec:<id>")
        return steps

    def _next_steps_empty(self, query: str) -> list[str]:
        return [
            "Расширьте корпус: python3 -m vostlit_research crawl --region caucasus --limit 25",
            "Проверьте варианты написания: python3 -m vostlit_research expand-variants " + repr(query),
            "Повторите: python3 -m vostlit_research research " + repr(query),
        ]


def render_markdown(result: SynthesisResult) -> str:
    """Render a SynthesisResult as a markdown report with clickable links."""
    lines = []
    lines.append(f"# Исследовательский ответ\n")
    lines.append(f"### Краткий вывод\n{result.verdict}\n")
    lines.append(f"{result.summary}\n")

    if result.findings:
        lines.append("### Найденные свидетельства\n")
        for i, f in enumerate(result.findings, 1):
            lines.append(f"**{i}. {f.claim}**")
            lines.append(f"  - Тип: {f.evidence_type} | Независимых свидетелей: {f.independent_witnesses} | Уверенность: {f.confidence}")
            lines.append(f"  - Формы: {', '.join(sorted(f.forms_attested))}")
            lines.append(f"  - Фрагменты:")
            for frag in f.supporting_fragments:
                title = frag.get("title") or "(без названия)"
                url = frag["url"]
                sid = frag["section_id"]
                quote = (frag.get("quote") or "")[:120].replace("\n", " ")
                lines.append(f"    - [{title}]({url}) — sec #{sid}")
                lines.append(f"      > «{quote}»")
            lines.append("")

    if result.identifications:
        lines.append("### Отождествления (редакторские)\n")
        for ident in result.identifications:
            lines.append(f"- «{ident['from_form']}» → **{ident.get('identified_as')}** "
                        f"([{ident['title']}]({ident['url']}) sec #{ident['section_id']})")
        lines.append("")

    if result.contradictions:
        lines.append("### Противоречия\n")
        for c in result.contradictions:
            lines.append(f"- Форма «{c['form']}» отождествляется по-разному: {c['different_identifications']}")
        lines.append("")

    lines.append("### Следующие шаги\n")
    for s in result.next_steps:
        lines.append(f"- {s}")
    return "\n".join(lines)
