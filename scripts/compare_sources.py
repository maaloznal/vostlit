#!/usr/bin/env python3
"""Skill helper: compare how several sources treat a claim.

Usage:
    python3 scripts/compare_sources.py "<claim>" <doc_id1> <doc_id2> [...]

For each source, prints the matching fragments (with section ids + URLs) so
the agent can judge agreement, contradiction, or silence. Does NOT adjudicate.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("claim")
    ap.add_argument("ids", nargs="+")
    args = ap.parse_args()

    env = {"PYTHONPATH": str(ROOT), "PATH": os.environ.get("PATH", "")}
    cmd = [sys.executable, "-m", "vostlit_research", "compare", args.claim] + args.ids
    res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        return res.returncode
    rep = json.loads(res.stdout)
    print(f"Claim: {rep['claim']}\n")
    for s in rep["sources"]:
        if "error" in s:
            print(f"  source {s['source_id']}: ERROR {s['error']}")
            continue
        print(f"  source {s['source_id']}: «{s.get('title')}»  ({s.get('author')})")
        print(f"    url: {s.get('canonical_url')}")
        print(f"    matches: {s['n_matches']}")
        for f in s["matching_fragments"][:5]:
            print(f"    - sec {f.get('section_id')}: {(f.get('snippet') or '')[:120]}")
        print()
    print("NOTE: this tool gathers evidence only. The independence/contradiction")
    print("judgment is the agent's — two excerpts deriving from one source are ONE witness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
