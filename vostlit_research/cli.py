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
    if st["documents"] == 0:
        print("  [HINT] corpus is empty — run `python3 scripts/seed_corpus.py`")
        print("         or `python3 -m vostlit_research crawl --region caucasus --limit 10`")
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


def cmd_extract_mentions(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        res = eng.extract_mentions(entity_id=args.entity_id, overwrite=args.overwrite,
                                   limit_per_variant=args.limit_per_variant)
        _print(res)
    finally:
        db.close()
    return 0


def cmd_toponym(args: argparse.Namespace) -> int:
    from .research.api import ResearchEngine
    from .search.engine import SearchFilters
    cfg, db = _open_engine(args)
    try:
        eng = ResearchEngine(db)
        f = None
        if args.region:
            f = SearchFilters(region=args.region)
        res = eng.search_engine.search_toponym(args.name, f, limit=args.limit)
        _print(res)
    finally:
        db.close()
    return 0


def cmd_note_add(args: argparse.Namespace) -> int:
    from .io import upsert_research_note
    from .models import ResearchNoteIn, FragmentRef
    cfg, db = _open_engine(args)
    try:
        sup: list[FragmentRef] = []
        con: list[FragmentRef] = []
        for spec in (args.supporting or []):
            sup.append(_parse_frag(spec))
        for spec in (args.contradicting or []):
            con.append(_parse_frag(spec))
        note = ResearchNoteIn(
            claim=args.claim, status=args.status,
            supporting_fragments=sup, contradicting_fragments=con,
            argumentation=args.argumentation,
            author_or_mechanism=args.author,
            confidence=args.confidence,
        )
        nid = upsert_research_note(db, note)
        print(nid)
    finally:
        db.close()
    return 0


def _parse_frag(spec: str):
    """Parse 'sec:487:url' or 'sec:487' or 'doc:7' into a FragmentRef."""
    from .models import FragmentRef
    parts = spec.split(":")
    if parts[0] == "sec" and len(parts) >= 2:
        return FragmentRef(section_id=int(parts[1]),
                           url=parts[2] if len(parts) > 2 else None)
    if parts[0] == "doc" and len(parts) >= 2:
        return FragmentRef(document_id=int(parts[1]),
                           url=parts[2] if len(parts) > 2 else None)
    # bare number -> section
    return FragmentRef(section_id=int(parts[0]))


def cmd_note_list(args: argparse.Namespace) -> int:
    cfg, db = _open_engine(args)
    try:
        rows = db.conn.execute(
            "SELECT id, claim, status, confidence, created_at FROM research_notes ORDER BY id"
        ).fetchall()
        _print([dict(r) for r in rows])
    finally:
        db.close()
    return 0


def cmd_note_show(args: argparse.Namespace) -> int:
    import json
    cfg, db = _open_engine(args)
    try:
        r = db.conn.execute("SELECT * FROM research_notes WHERE id=?", (int(args.id),)).fetchone()
        if r is None:
            print(f"note {args.id} not found", file=sys.stderr)
            return 1
        d = dict(r)
        d["supporting_fragments"] = json.loads(d.get("supporting_fragments") or "[]")
        d["contradicting_fragments"] = json.loads(d.get("contradicting_fragments") or "[]")
        d["change_history"] = json.loads(d.get("change_history") or "[]")
        _print(d)
    finally:
        db.close()
    return 0


def cmd_note_verify(args: argparse.Namespace) -> int:
    """Re-run the exact searches cited in a note's supporting fragments and
    confirm each still resolves to a real section. Reproducibility check."""
    import json
    cfg, db = _open_engine(args)
    try:
        from .research.api import ResearchEngine
        eng = ResearchEngine(db)
        r = db.conn.execute("SELECT * FROM research_notes WHERE id=?", (int(args.id),)).fetchone()
        if r is None:
            print(f"note {args.id} not found", file=sys.stderr)
            return 1
        sup = json.loads(r["supporting_fragments"] or "[]")
        report = {"note_id": int(args.id), "claim": r["claim"], "checked": [], "missing": []}
        for frag in sup:
            sid = frag.get("section_id")
            if sid is None:
                report["missing"].append({"fragment": frag, "reason": "no section_id"})
                continue
            sec = db.conn.execute("SELECT id, document_id, text FROM document_sections WHERE id=?", (sid,)).fetchone()
            if sec is None:
                report["missing"].append({"section_id": sid, "reason": "section no longer exists"})
            else:
                report["checked"].append({"section_id": sid, "document_id": sec["document_id"],
                                           "text_preview": (sec["text"] or "")[:120]})
        report["all_resolvable"] = len(report["missing"]) == 0
        _print(report)
    finally:
        db.close()
    return 0 if False else 0  # always 0: this is a report, not a pass/fail


def cmd_works(args: argparse.Namespace) -> int:
    """Group documents into logical 'works' by URL path prefix.

    For .phtml docs: /Texts/rus<N>/<slug>/  -> one work.
    For .htm docs:   /Texts/Dokumenty/<region>/<century>/<period>/<slug>/ -> one work.
    """
    cfg, db = _open_engine(args)
    try:
        rows = db.conn.execute("SELECT id, canonical_url, title, author, page_type FROM documents ORDER BY canonical_url").fetchall()
        works: dict[str, list[dict]] = {}
        for r in rows:
            prefix = _work_prefix(r["canonical_url"])
            if prefix is None:
                continue
            works.setdefault(prefix, []).append(dict(r))
        out = []
        for prefix, docs in sorted(works.items()):
            if args.min and len(docs) < args.min:
                continue
            out.append({
                "work_prefix": prefix,
                "n_parts": len(docs),
                "title": docs[0]["title"],
                "author": docs[0]["author"],
                "parts": [{"id": d["id"], "url": d["canonical_url"], "page_type": d["page_type"]} for d in docs],
            })
        _print(out)
    finally:
        db.close()
    return 0


def _work_prefix(url: str) -> str | None:
    """Return the path prefix that identifies a logical 'work'.

    A work is a directory that contains multiple part-files:
      - /Texts/rus<N>/<slug>/        (e.g. /Texts/rus/Iordan/ holds text1.phtml, text2.phtml, ...)
      - /Texts/Dokumenty/<region>/<century>/<period>/<slug>/
    """
    from urllib.parse import urlsplit
    import re
    path = urlsplit(url).path
    # the file is the last path component; the work-prefix is everything before it
    # (only if there is a real file, i.e. path doesn't end with '/')
    if path.endswith("/"):
        return None
    prefix = path.rsplit("/", 1)[0] if "/" in path else None
    if prefix is None:
        return None
    # accept only known work-directory shapes:
    #   /Texts/rus<N>/<slug>   e.g. /Texts/rus/Iordan, /Texts/rus13/Sirvan_Derbend
    #   /Texts/Dokumenty/<region>/<century>/<period>/<slug>
    if re.match(r"/Texts/rus[^/]*/[^/]+$", prefix):
        return prefix
    if re.match(r"/Texts/Dokumenty/[^/]+/[^/]+/[^/]+/[^/]+$", prefix):
        return prefix
    return None


def cmd_regions(args: argparse.Namespace) -> int:
    """List the known region catalogs (from discover.REGIONS)."""
    from .collector.discover import REGIONS
    _print([{"slug": k, "file": v} for k, v in REGIONS.items()])
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

    # --- new: mention extraction, toponym search, research notes, works ---
    sp = sub.add_parser("extract-mentions",
                        help="heuristically extract name-variant mentions from body text (candidates only)")
    sp.add_argument("--entity-id", type=int, default=None, help="restrict to one entity")
    sp.add_argument("--overwrite", action="store_true", help="re-extract (delete prior heuristic mentions for the same variant+section)")
    sp.add_argument("--limit-per-variant", type=int, default=50)
    sp.set_defaults(func=cmd_extract_mentions)

    sp = sub.add_parser("toponym",
                        help="full toponym-search algorithm -> candidate table (master prompt §11)")
    sp.add_argument("name"); sp.add_argument("--region"); sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_toponym)

    sp = sub.add_parser("note", help="research notes (add/list/show/verify)")
    sp_sub = sp.add_subparsers(dest="note_cmd", required=True)
    sp_a = sp_sub.add_parser("add", help="add a research note")
    sp_a.add_argument("--claim", required=True)
    sp_a.add_argument("--status", required=True,
                      choices=["source_fact", "interpretation", "hypothesis", "refuted"])
    sp_a.add_argument("--confidence", default="possible",
                      choices=["verified", "probable", "possible", "unestablished"])
    sp_a.add_argument("--supporting", action="append",
                      help="fragment spec: 'sec:487' or 'sec:487:URL' or 'doc:7' (repeatable)")
    sp_a.add_argument("--contradicting", action="append")
    sp_a.add_argument("--argumentation", default=None)
    sp_a.add_argument("--author", default=None)
    sp_a.set_defaults(func=cmd_note_add)
    sp_l = sp_sub.add_parser("list", help="list notes")
    sp_l.set_defaults(func=cmd_note_list)
    sp_s = sp_sub.add_parser("show", help="show one note")
    sp_s.add_argument("id"); sp_s.set_defaults(func=cmd_note_show)
    sp_v = sp_sub.add_parser("verify", help="verify a note's cited fragments still resolve")
    sp_v.add_argument("id"); sp_v.set_defaults(func=cmd_note_verify)

    sp = sub.add_parser("works", help="group documents into logical works by URL prefix")
    sp.add_argument("--min", type=int, default=1, help="only works with >= N parts")
    sp.set_defaults(func=cmd_works)

    sp = sub.add_parser("regions", help="list known region catalog slugs")
    sp.set_defaults(func=cmd_regions)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
