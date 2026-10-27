"""Command-line interface.

Run with: ``python -m vostlit_research <command> [args]``.

Every command has ``--help``. Commands never perform destructive operations.
Network-touching commands (``audit-site``, ``crawl``) are explicit and
polite (see collector/http.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .config import load_config
from .db import Database


def _print(data: Any) -> None:
    if isinstance(data, (dict, list)):
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(data)


# ---------------------------------------------------------------------- doctor

def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    cfg.ensure_dirs()
    print(f"vostlit_research {__version__}")
    print(f"  db_path            : {cfg.db_path}")
    print(f"  archive_dir        : {cfg.archive_dir}")
    print(f"  base_url           : {cfg.base_url}")
    print(f"  store_html         : {cfg.store_html}")
    print(f"  request_delay      : {cfg.request_delay}s")
    print(f"  max_pages_per_run  : {cfg.max_pages_per_run}")
    print(f"  semantic_provider  : {cfg.semantic_provider}")
    ok = True
    try:
        db = Database(cfg.db_path)
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] cannot open db: {e}")
        return 2
    print(f"  schema_version     : {db.schema_version()}")
    fts = db.fts5_available()
    print(f"  fts5_available     : {fts}")
    if not fts:
        ok = False
    st = db.stats()
    print(f"  documents          : {st['documents']}")
    print(f"  document_versions  : {st['document_versions']}")
    print(f"  document_sections  : {st['document_sections']}")
    print(f"  entities           : {st['entities']}")
    print(f"  name_variants      : {st['name_variants']}")
    print(f"  mentions           : {st['mentions']}")
    print(f"  research_notes     : {st['research_notes']}")
    print(f"  documents_by_status: {st['documents_by_status']}")
    print(f"  documents_by_type  : {st['documents_by_type']}")
    db.close()
    print("  [OK] environment ready" if ok and fts else "  [FAIL] see above")
    return 0 if (ok and fts) else 1


# ---------------------------------------------------------------------- audit-site

def cmd_audit_site(args: argparse.Namespace) -> int:
    from .collector.http import HttpClient
    from .collector.parser import parse_page
    cfg = load_config(args.config)
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        urls = args.urls or [cfg.base_url]
        out: list[dict] = []
        for u in urls:
            try:
                res = http.fetch(u)
                p = parse_page(u, res.content, charset=_ct_charset(res.content_type))
                out.append({
                    "url": u,
                    "final_url": res.final_url,
                    "status": res.status,
                    "content_type": res.content_type,
                    "bytes": len(res.content),
                    "page_type": p.page_type,
                    "title": p.title,
                    "author": p.author,
                    "n_sections": len(p.sections),
                    "n_links": len(p.links),
                    "n_images": len(p.images),
                    "warnings": p.warnings,
                })
            except Exception as e:  # noqa: BLE001
                out.append({"url": u, "error": str(e)})
        _print(out)
        return 0
    finally:
        http.close()
        db.close()


# ---------------------------------------------------------------------- crawl

def cmd_crawl(args: argparse.Namespace) -> int:
    from .collector.crawl import Crawler
    cfg = load_config(args.config)
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    crawler = Crawler(cfg, db)
    try:
        report = crawler.crawl(
            regions=args.region or None,
            letters=args.letter or None,
            seeds=args.seed or None,
            include_home=args.home,
            limit=args.limit,
            force=args.force,
            discover_only=args.discover_only,
        )
    finally:
        crawler.http.close()
        db.close()
    _print(report.as_dict())
    return 0 if report.errors == 0 else 1


# ---------------------------------------------------------------------- import/export

def cmd_import_jsonl(args: argparse.Namespace) -> int:
    from .io import import_jsonl
    cfg = load_config(args.config)
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    try:
        counts = import_jsonl(db, args.file, archive_root=cfg.archive_dir)
    finally:
        db.close()
    _print(counts)
    return 0 if counts["errors"] == 0 else 1


def cmd_export(args: argparse.Namespace) -> int:
    from .io import export_jsonl
    cfg = load_config(args.config)
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    try:
        if args.format == "jsonl":
            n = export_jsonl(db, args.output, include_sections=not args.no_sections)
        else:
            print(f"unsupported format: {args.format}", file=sys.stderr)
            return 2
    finally:
        db.close()
    print(f"exported {n} records to {args.output}")
    return 0


# ---------------------------------------------------------------------- search cmds

def _open_engine(args):
    cfg = load_config(args.config)
    db = Database(cfg.db_path)
    return cfg, db


def cmd_search(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        res = eng.search_documents(args.query, limit=args.limit,
                                   region=args.region, author=args.author,
                                   source_type=args.source_type,
                                   date_from=args.date_from, date_to=args.date_to)
        if not res:
            print("No results. The corpus may be empty — run `python -m vostlit_research doctor` and import/crawl first.")
        else:
            _print(res)
    finally:
        db.close()
    return 0


def cmd_search_exact(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        res = eng.search_exact(args.phrase, limit=args.limit, region=args.region, author=args.author)
        _print(res)
    finally:
        db.close()
    return 0


def cmd_search_variants(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        res = eng.search_name_variants(args.name, limit=args.limit)
        _print(res)
    finally:
        db.close()
    return 0


def cmd_search_fuzzy(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        res = eng.search_fuzzy(args.name, threshold=args.threshold, limit=args.limit)
        _print(res)
    finally:
        db.close()
    return 0


def cmd_document(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        doc = eng.get_document(int(args.id))
        if doc is None:
            print(f"document {args.id} not found", file=sys.stderr)
            return 1
        _print(doc)
    finally:
        db.close()
    return 0


def cmd_section(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        _print(eng.get_section(int(args.id)))
    finally:
        db.close()
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        _print(eng.get_context(int(args.id), before=args.before, after=args.after))
    finally:
        db.close()
    return 0


def cmd_mentions(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        _print(eng.find_mentions(args.name, limit=args.limit))
    finally:
        db.close()
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        _print(eng.compare_sources(args.claim, [int(x) for x in args.ids]))
    finally:
        db.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    cfg, db = _open_engine(args)
    try:
        _print(db.stats())
    finally:
        db.close()
    return 0


def cmd_rebuild_fts(args: argparse.Namespace) -> int:
    cfg, db = _open_engine(args)
    try:
        _print(db.rebuild_all_fts())
    finally:
        db.close()
    return 0


def cmd_by_region(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        _print(eng.search_by_region(args.region, args.query, limit=args.limit))
    finally:
        db.close()
    return 0


def cmd_bibliography(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        _print(eng.get_document_bibliography(int(args.id)))
    finally:
        db.close()
    return 0


# ---------------------------------------------------------------------- helpers

def _ct_charset(content_type: str) -> str | None:
    if "charset=" in (content_type or "").lower():
        return content_type.split("charset=", 1)[1].split(";")[0].strip()
    return "windows-1251"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m vostlit_research",
        description="vostlit_research — reproducible research over Vostlit.info sources.",
    )
    p.add_argument("--config", default=None, help="path to config.toml (default: config/config.toml)")
    p.add_argument("--version", action="version", version=f"vostlit_research {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("doctor", help="check environment, db, FTS5, config")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("audit-site", help="fetch & classify given URLs (polite)")
    sp.add_argument("urls", nargs="*", help="URLs to fetch (default: homepage)")
    sp.set_defaults(func=cmd_audit_site)

    sp = sub.add_parser("crawl", help="discover + fetch + parse + store")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--region", action="append", help="region slug (e.g. caucasus); repeatable")
    sp.add_argument("--letter", action="append", help="Cyrillic letter slug (e.g. G); repeatable")
    sp.add_argument("--seed", action="append", help="explicit URL; repeatable")
    sp.add_argument("--home", action="store_true", help="also harvest the homepage featured links")
    sp.add_argument("--force", action="store_true", help="re-fetch even already-parsed documents")
    sp.add_argument("--discover-only", action="store_true", help="only build the inventory, no text fetch")
    sp.set_defaults(func=cmd_crawl)

    sp = sub.add_parser("import-jsonl", help="import a JSONL corpus")
    sp.add_argument("file")
    sp.set_defaults(func=cmd_import_jsonl)

    sp = sub.add_parser("export", help="export the corpus to JSONL")
    sp.add_argument("output")
    sp.add_argument("--format", default="jsonl", choices=["jsonl"])
    sp.add_argument("--no-sections", action="store_true")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("search", help="hybrid search (exact+fts+variants+fuzzy)")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--region"); sp.add_argument("--author")
    sp.add_argument("--source-type"); sp.add_argument("--date-from"); sp.add_argument("--date-to")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("search-exact", help="exact phrase search (preserves spelling)")
    sp.add_argument("phrase")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--region"); sp.add_argument("--author")
    sp.set_defaults(func=cmd_search_exact)

    sp = sub.add_parser("search-variants", help="lookup the name-variant dictionary")
    sp.add_argument("name"); sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_search_variants)

    sp = sub.add_parser("search-fuzzy", help="fuzzy name search (candidates only)")
    sp.add_argument("name"); sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--threshold", type=float, default=0.72)
    sp.set_defaults(func=cmd_search_fuzzy)

    sp = sub.add_parser("document", help="show a document (with current version)")
    sp.add_argument("id")
    sp.set_defaults(func=cmd_document)

    sp = sub.add_parser("section", help="show one section")
    sp.add_argument("id")
    sp.set_defaults(func=cmd_section)

    sp = sub.add_parser("context", help="show a section with surrounding context")
    sp.add_argument("id"); sp.add_argument("--before", type=int, default=1); sp.add_argument("--after", type=int, default=1)
    sp.set_defaults(func=cmd_context)

    sp = sub.add_parser("mentions", help="find mentions of a name")
    sp.add_argument("name"); sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_mentions)

    sp = sub.add_parser("compare", help="compare sources for a claim")
    sp.add_argument("claim"); sp.add_argument("ids", nargs="+")
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("by-region", help="list/search documents in a region")
    sp.add_argument("region"); sp.add_argument("query", nargs="?"); sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_by_region)

    sp = sub.add_parser("bibliography", help="show a document's bibliography")
    sp.add_argument("id")
    sp.set_defaults(func=cmd_bibliography)

    sp = sub.add_parser("stats", help="corpus statistics")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("rebuild-fts", help="drop & rebuild all FTS5 indexes")
    sp.set_defaults(func=cmd_rebuild_fts)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
