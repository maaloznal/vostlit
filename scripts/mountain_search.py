#!/usr/bin/env python3
"""Mountain-search scenario (master prompt §11).

End-to-end implementation of the historical-mountain identification
algorithm. Given a candidate toponym (e.g. "гора Джалдари-меер" near
Гумбет, Дагестан, on an 1839 map), this script:

  1. Decomposes the query (toponym + region + neighbour societies).
  2. Expands variants (pre-reform, transliterations, geo-generic-stripped).
  3. Runs the search ladder (exact → fts → variants → fuzzy).
  4. Collects a candidate table with sources, dates, and arguments.
  5. Checks each candidate's date vs. the map date, region fit, and whether
     multiple INDEPENDENT sources attest the name.
  6. Emits a CAUTIOUS verdict — never asserts identity without corroboration.

Usage:
    python3 scripts/mountain_search.py "<toponym>" [--region Дагестан] [--year 1839] [--limit N]

Output: a structured JSON report + a human-readable summary to stderr.
Nothing is invented: if the corpus has no attestation, the verdict is
"Не установлено" with concrete next steps.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vostlit_research.config import Config
from vostlit_research.db import Database
from vostlit_research.research.api import ResearchEngine
from vostlit_research.search.engine import SearchFilters
from vostlit_research import textnorm


# Neighbouring societies of Гумбет (for region-fit checks). Sourced from the
# scholarly literature, NOT auto-inferred; the agent must verify in-context.
GUMBET_NEIGHBOURS = ["Салатавия", "Андийское общество", "Авария", "Койсубу"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("toponym", help='candidate toponym, e.g. "гора Джалдари-меер"')
    ap.add_argument("--region", default="Дагестан", help="expected region (default: Дагестан)")
    ap.add_argument("--year", default=None, help="map/source date (e.g. 1839) for date-fit checks")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()

    cfg = Config()
    db = Database(cfg.db_path)
    try:
        eng = ResearchEngine(db)
        f = SearchFilters(region=args.region) if args.region else None

        # 1. decompose
        core = textnorm.strip_geo_generic(args.toponym)
        forms = [args.toponym]
        if core and core != textnorm.normalise_search(args.toponym):
            forms.append(core)

        # 2-4. run the toponym algorithm
        table = eng.search_engine.search_toponym(args.toponym, f, limit=args.limit)

        # 5. candidate-level analysis: date fit, region fit, independence
        map_year = int(args.year) if args.year else None
        for c in table["candidates"]:
            # date fit
            doc_year = c.get("publication_year")
            c["date_fit"] = _date_fit(doc_year, map_year)
            # region fit
            c["region_fit"] = (c.get("region") or "") == args.region
            # snippet present (real evidence) or not
            c["has_verbatim_quote"] = bool(c.get("snippet"))

        # independence: group candidates by document; 2+ candidates from the
        # SAME document count as ONE witness.
        docs = {}
        for c in table["candidates"]:
            docs.setdefault(c["document_id"], []).append(c)
        independent_witnesses = sum(1 for d, cs in docs.items() if any(c["has_verbatim_quote"] for c in cs))

        # 6. verdict
        n_exact = sum(1 for c in table["candidates"] if c["matched_as"] == "exact" and c["has_verbatim_quote"])
        n_variant = sum(1 for c in table["candidates"] if c["matched_as"] == "variant")
        if n_exact >= 2 and independent_witnesses >= 2:
            verdict = "Подтверждено"
        elif n_exact >= 1 and independent_witnesses >= 1:
            verdict = "Вероятно"
        elif (n_exact + n_variant) >= 1:
            verdict = "Возможно"
        else:
            verdict = "Не установлено"

        report = {
            "query": {
                "toponym": args.toponym,
                "core_toponym": core,
                "forms_searched": forms,
                "region": args.region,
                "map_year": map_year,
            },
            "candidate_table": table["candidates"],
            "n_candidates": table["n_candidates"],
            "n_exact_verbatim": n_exact,
            "n_variant": n_variant,
            "independent_witnesses": independent_witnesses,
            "verdict": verdict,
            "next_steps": _next_steps(verdict, args, core),
            "note": table["note"],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))

        # human summary to stderr
        print(f"\n=== Mountain-search: {args.toponym} ===", file=sys.stderr)
        print(f"core toponym: {core}", file=sys.stderr)
        print(f"forms searched: {forms}", file=sys.stderr)
        print(f"candidates: {table['n_candidates']} (exact verbatim: {n_exact}, variant: {n_variant})", file=sys.stderr)
        print(f"independent witnesses: {independent_witnesses}", file=sys.stderr)
        print(f"VERDICT: {verdict}", file=sys.stderr)
        if verdict == "Не установлено":
            print("  → corpus has no attestation; extend with crawl (see next_steps)", file=sys.stderr)
        return 0
    finally:
        db.close()


def _date_fit(doc_year: str | None, map_year: int | None) -> str:
    if not doc_year or not map_year:
        return "unknown"
    try:
        dy = int(str(doc_year)[:4])
    except (ValueError, TypeError):
        return "unknown"
    # a source written within ~50 years of the map date is "close";
    # within the source's own period is "contemporary"; much later is "later"
    diff = dy - map_year
    if abs(diff) <= 10:
        return "contemporary"
    if abs(diff) <= 50:
        return "close"
    if diff > 50:
        return "later"
    return "earlier"


def _next_steps(verdict: str, args: argparse.Namespace, core: str) -> list[str]:
    steps = []
    if verdict == "Не установлено":
        steps.append("extend the corpus: python3 -m vostlit_research crawl --region caucasus --limit 25")
        steps.append("after crawl, re-run: python3 scripts/mountain_search.py " + repr(args.toponym) + f" --region {args.region}")
        steps.append(f"also search the variant dictionary for the core «{core}» and confirm any candidate in-context")
    elif verdict in ("Возможно", "Вероятно"):
        steps.append("read each candidate's context with `python3 -m vostlit_research context <section_id> --before 2 --after 2`")
        steps.append("check the document date vs. the map date (date_fit field)")
        steps.append("verify independence: two excerpts from one chronicle = ONE witness")
        steps.append("only promote to Подтверждено when >=2 independent verbatim attestations exist")
    else:  # Подтверждено
        steps.append("record a research_note with status=source_fact citing the supporting section_ids")
        steps.append("python3 -m vostlit_research note add --claim '...' --status source_fact --supporting sec:<id> ...")
    return steps


if __name__ == "__main__":
    raise SystemExit(main())
