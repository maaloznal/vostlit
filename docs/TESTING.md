# Testing

## Running the suite

```bash
cd <project-root>
python3 -m pytest tests/ -c pyproject.toml
```

Current state: **102 passed, 2 skipped** (v0.3.1). The 2 skips are live-site
integration tests (see below). Test files:
- `test_parser.py` (13) — verified page-type parsing
- `test_normalize.py` (12) — text normalisation, fuzzy, URL canonicalisation
- `test_store.py` (7) — dedup, versioning, FTS sync, import/export
- `test_search.py` (11) — exact/fts/variant/fuzzy/context/hybrid
- `test_cli_security.py` (9) — CLI + archive path safety
- `test_v02_improvements.py` (14) — frameset, mentions, toponym, notes, works
- `test_p0_p1_regression.py` (10) — P0 security + section-id + search F1/F2/F3
- `test_discovery_fixes.py` (15) — v0.3.1: _is_doc_url roots, chrono parser, catalogs
- `test_redirect_http.py` (9) — v0.3.1: real HTTP-level redirect/error tests via MockTransport
- `test_e2e_pipeline.py` (2) — v0.3.1: full pipeline on persistent DB
- `test_integration_live.py` (2, skipped by default) — live site

## What is covered (master prompt §15 checklist)

| # | Requirement | Test file |
|---|-------------|-----------|
| 1 | Document page parsing | `test_parser.py` (5 doc types) |
| 2 | Title & author extraction | `test_parser.py::test_phtml_doc_*` |
| 3 | Body text extraction | `test_parser.py` |
| 4 | Footnotes & bibliography preservation | `test_parser.py` (notes_page, inline notes, citation) |
| 5 | Non-standard encoding (windows-1251) | `test_parser.py::test_decoder_handles_windows1251` |
| 6 | Whitespace & Unicode normalisation | `test_normalize.py` |
| 7 | Original spelling preserved | `test_store.py::test_sections_written_and_text_lower` |
| 8 | Exact phrase search | `test_search.py::test_exact_search_*` |
| 9 | Full-text search | `test_search.py::test_fts_search_*` |
| 10 | Name-variant search | `test_search.py::test_variant_search_*` |
| 11 | Region/author/date filters | `test_search.py::test_filter_by_region` |
| 12 | No duplicates on re-import | `test_store.py::test_reimport_same_text_is_idempotent`, `test_dedup_by_canonical_url` |
| 13 | Network error behaviour | `test_cli_security.py` (refusal paths); `http.py` retries |
| 14 | Empty document behaviour | `test_store.py::test_empty_document_is_discovered_not_parsed` |
| 15 | Citation correctness | `test_parser.py` (publication_year, citation prefix) |
| 16 | Document↔fragment↔mention link | `test_search.py::test_find_mentions_combines_table_and_text` |
| 17 | Works without semantic model | `test_search.py::test_empty_corpus_honest` (no-op provider) |
| 18 | Export & re-import | `test_store.py::test_import_export_roundtrip` |
| 19 | Schema migration | `test_cli_security.py::test_crawl_log_records_fetches`; `doctor` checks `schema_version` |
| 20 | Untrusted HTML safety | `test_cli_security.py::test_parser_does_not_execute_scripts`, `test_parser_handles_malformed_html`, `test_archive_path_escape_refused` |

Plus CLI tests: `test_cli_doctor`, `test_cli_stats_empty`, `test_cli_search_on_empty_corpus_is_honest`.

## Fixtures

`tests/fixtures/` holds 13 real pages saved during the site audit (see
`fixtures_manifest.json` with sha256 + source URL + fetch time). They are
windows-1251 bytes; tests decode them the same way the live parser does.
`tests/fixtures/README.md` (written by the audit subagent) notes these are
site snapshots for offline parser testing only and must not be redistributed.

A test must never be confused with a real corpus document: fixtures are
loaded into a *temp* DB per test, never into the project's `data/vostlit.db`.

## Live-site integration tests

`tests/test_integration_live.py` is **skipped by default**. Run explicitly:

```bash
VR_INTEGRATION=1 python3 -m pytest tests/test_integration_live.py -s
```

It fetches ≤2 pages with the polite client and asserts the parser handles
them. If `vostlit.info` is unreachable, it skips (never fails).

## What tests do NOT prove

- They do **not** prove historical truth — only that the pipeline is
  mechanically correct and reproducible.
- They do not exhaustively cover every page type on the live site (only the
  13 fixtures). New page types will be recorded as `skipped` with a warning
  by the crawler, and should be added as fixtures when found.

## Adding a new fixture

1. Fetch the page during a `crawl` or `audit-site` run (it is auto-archived
   by sha256 under `data/archive/`).
2. Copy a representative slice to `tests/fixtures/<name>.html` (raw bytes).
3. Add an entry to `fixtures_manifest.json`.
4. Add a parser test asserting the key fields.
