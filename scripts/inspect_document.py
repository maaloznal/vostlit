#!/usr/bin/env python3
"""Skill helper: inspect a document with its current version and sections.

Usage:
    python3 scripts/inspect_document.py <document_id> [--sections] [--limit N]

Prints the document metadata, the extraction provenance (method, parser
version, content hash, warnings), and (optionally) its sections in order.
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
    ap.add_argument("document_id")
    ap.add_argument("--sections", action="store_true", help="also list sections")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    env = {"PYTHONPATH": str(ROOT), "PATH": os.environ.get("PATH", "")}
    cmd = [sys.executable, "-m", "vostlit_research", "document", args.document_id]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        return res.returncode
    doc = json.loads(res.stdout)
    print(f"Document #{doc['id']}")
    print(f"  title    : {doc.get('title')}")
    print(f"  author   : {doc.get('author')}")
    print(f"  type     : {doc.get('page_type')}  region: {doc.get('region')}")
    print(f"  doc date : {doc.get('original_creation_date')}  pub year: {doc.get('publication_year')}")
    print(f"  edition  : {doc.get('publication_title')}")
    print(f"  url      : {doc.get('canonical_url')}")
    print(f"  status   : {doc.get('status')}  content_hash: {doc.get('content_hash')}")
    print(f"  parser   : {doc.get('parser_version')}  method: {doc.get('extraction_method')}")
    if doc.get("extraction_warnings"):
        print(f"  warnings : {doc['extraction_warnings']}")
    if args.sections:
        # fetch sections via a direct DB query (sections aren't in the document cmd)
        sys.path.insert(0, str(ROOT))
        from vostlit_research.db import Database
        from vostlit_research.config import Config
        cfg = Config()
        db = Database(cfg.db_path)
        try:
            rows = db.conn.execute(
                "SELECT sequence_number, section_type, heading, text, page_number FROM document_sections WHERE document_id=? ORDER BY sequence_number LIMIT ?",
                (int(args.document_id), args.limit),
            ).fetchall()
            print(f"\n  -- sections (first {len(rows)}) --")
            for r in rows:
                head = f"«{r['heading']}» " if r["heading"] else ""
                txt = (r["text"] or "")[:140].replace("\n", " ")
                pg = f" [p.{r['page_number']}]" if r["page_number"] else ""
                print(f"  {r['sequence_number']:>3} {r['section_type']:<14} {head}{txt}{pg}")
        finally:
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
