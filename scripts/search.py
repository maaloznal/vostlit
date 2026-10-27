#!/usr/bin/env python3
"""Skill helper: run a hybrid search and print results in a readable form.

Usage:
    python3 scripts/search.py "<query>" [--region R] [--author A] [--limit N]

This is a convenience wrapper around `python -m vostlit_research search`.
It enforces the rule that every result must carry a verifiable document+section
link; results without one are printed with a warning.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query")
    ap.add_argument("--region", default=None)
    ap.add_argument("--author", default=None)
    ap.add_argument("--source-type", dest="source_type", default=None)
    ap.add_argument("--date-from", dest="date_from", default=None)
    ap.add_argument("--date-to", dest="date_to", default=None)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    cmd = [sys.executable, "-m", "vostlit_research", "search", args.query,
           "--limit", str(args.limit)]
    for flag, val in (("--region", args.region), ("--author", args.author),
                      ("--source-type", args.source_type),
                      ("--date-from", args.date_from), ("--date-to", args.date_to)):
        if val:
            cmd += [flag, val]
    env = {"PYTHONPATH": str(ROOT), "PATH": __import__("os").environ.get("PATH", "")}
    res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        return res.returncode
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        print(res.stdout)
        return 0
    if not data:
        print("No results. The corpus may be empty — run `doctor` and `crawl`/`import-jsonl` first.")
        return 0
    for r in data:
        verifiable = bool(r.get("document_id") and r.get("canonical_url"))
        flag = "" if verifiable else "  ⚠ no verifiable source link"
        print(f"[doc {r.get('document_id')}#sec {r.get('section_id')}] "
              f"({r.get('match_type')}, {r.get('confidence')}){flag}")
        print(f"  title : {r.get('title')}")
        print(f"  author: {r.get('author')}  region: {r.get('region')}  year: {r.get('publication_year')}")
        print(f"  url   : {r.get('canonical_url')}")
        if r.get("snippet"):
            print(f"  quote : {r['snippet']}")
        print(f"  why   : {r.get('explanation')}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
