# Changelog

All notable changes to vostlit-research. Dates are Europe/Moscow.

## [0.3.0] — 2025-10-27

Master Upgrade Mission: P0 security & reproducibility hardening + P1 search
fixes + inventory/resume CLI. Driven by 4 parallel subagent audits (site
coverage, schema, search quality, security) + 1 independent QA pass.

### Security (P0 — confirmed by SECURITY_AUDIT.md + QA_VERIFICATION.md)
- **D-1 redirect leak (CRITICAL, fixed):** `httpx.Client(follow_redirects=False)`
  + manual per-hop `_check_scope` on every redirect target BEFORE the request
  is sent. Offsite redirects are now refused without ever sending a request
  to the attacker host.
- **D-2 allowed_sections bypass (CRITICAL, fixed):** removed `/` from the
  default `allowed_sections` (it bypassed the path check since every path
  starts with `/`). Homepage handled explicitly in `_check_scope`.
- **D-3 silent 4xx/5xx parsing (CRITICAL, fixed):** added explicit
  `status_code >= 400` check that raises `HTTPStatusError` (429/503 →
  `_RetryableStatus` with `Retry-After` honor). Error bodies are no longer
  parsed as document content.
- **D-4 response size cap (HIGH, fixed):** streaming read with 25 MB cap;
  `TooLargeResponseError` on overflow.
- **D-8 resp.elapsed RuntimeError (MEDIUM, fixed):** elapsed computed with
  `time.monotonic()`, never from `resp.elapsed`.
- **D-6/D-7 scheme/port validation:** `file://`/`ftp://`/`gopher://` refused;
  non-default ports (≠ 80/443) refused.
- Regression tests: `tests/test_p0_p1_regression.py` (D-1/D-2/D-6/D-7 +
  portability + section-id + F1/F2/F3 + inventory).

### Reproducibility (P0 — confirmed by SCHEMA_AUDIT.md + QA_VERIFICATION.md)
- **B-§3.1 section-id instability (CRITICAL, fixed):** on unchanged re-import,
  `store.upsert_document` no longer DELETEs+re-INSERTs sections (which
  recycled AUTOINCREMENT ids and dangled every `mentions.section_id` /
  `evidence_section_id` / note fragment). Added `document_sections.stable_key`
  (sha1 of canonical_url:version_number:sequence_number) — stable across
  re-parses. Migration v1→v2 + backfill. Verified: id stays 1→1 on re-import.
- **New tables (P2):** `research_note_fragments` (FK-protected fragment refs,
  replaces JSON blobs), `document_relations` (verifiable work/edition
  relationships with `verification_status`).
- `schema_version` bumped to 2.

### Search quality (P1 — confirmed by SEARCH_AUDIT.md + QA_VERIFICATION.md)
- **F1 variants/fuzzy ignore filters (HIGH, fixed):** `search_variants` and
  `search_fuzzy` now call `_allowed_doc_ids` and filter both SQL rows AND FTS
  hits by the evidence document's region/author.
- **F2 Cyrillic case-sensitivity (HIGH, fixed):** region/author matching moved
  to Python `fold_for_match` (SQLite `LOWER()` is ASCII-only). `search_by_region`
  / `search_by_author` listing APIs also fixed (N1 from QA).
- **F3 date filter semantics (HIGH, fixed):** date filter now prefers
  `original_creation_date` (event date) over `publication_year`, and compares
  numerically via `CAST(substr(...) AS INTEGER)` instead of lexicographically.
  A 1792 primary source published in 2003 is now correctly found by
  `search_by_date("1790","1800")`.

### Corpus management (P1)
- **`inventory` CLI:** coverage report (discovered/parsed/skipped/error/stale/
  crawl_log_errors/by_type/unsupported_page_types) — all from real DB state.
- **`resume` CLI:** resume crawl for discovered/error documents without
  re-fetching parsed/unchanged.
- **Portability (P0):** removed all hardcoded `/home/z/my-project/vostlit-research`
  paths from code and tests; use `Path(__file__).resolve().parent.parent`.
- **Version sync:** pyproject/__init__/SKILL all at 0.3.0.
- **seed_corpus.py:** uses `load_config()` (applies `VOSTLIT_*` env) so
  `VOSTLIT_DB_PATH` works in subprocesses.

### Tests
- 77 passing (was 67), 2 skipped (live). New: `test_p0_p1_regression.py`
  (10 tests covering D-1/D-2/D-6/D-7/B-§3.1/stable_key-backfill/F1/F2/F3/inventory).

### Documentation
- New: UPGRADE_BASELINE, SITE_COVERAGE_AUDIT, SCHEMA_AUDIT, SEARCH_AUDIT,
  SECURITY_AUDIT, QA_VERIFICATION.
- Updated: SKILL (inventory/resume commands), AGENT_INTEGRATION, TESTING.

### Known limitations (from QA_VERIFICATION.md)
- `_is_doc_url` still requires `/texts/` → misses `/common/`, `/Repertorium/`,
  the on-site search form (N4, site-coverage P0 — not yet fixed).
- `chrono.phtml` yields 0 sections (table-based content; N4).
- `region_catalog`/`alpha_index` not in `fetch_page_types` (N4).
- `datetime.utcnow()` deprecation resolved (N5).

## [0.2.0] — 2025-10-27

Major skill improvements: frameset deep-parsing, heuristic mention
extraction, the §11 toponym candidate-table algorithm, research-note CLI
with reproducibility verification, and corpus-utility commands.

### Added
- **Frameset parser** (`page_type='frameset'`): verified against real
  `frame*.htm` pages (Nogmov `framevved1.htm` — `<frameset rows="*,15%">`
  with `Hauptframe` + `Fussnoten`). The parser extracts inner-frame URLs,
  infers each frame's role (main/notes/nav), exposes them as structured
  `FrameRef`s AND as `links` (kind='frame'). The collector now follows
  frameset inner frames automatically (within the page cap) and stores each
  as its own document linked back via `source_metadata.parent_frameset_url`.
  Previously these pages were misparsed as empty bare-.htm documents.
- **Heuristic mention extraction** (`extract-mentions` CLI + `ResearchEngine.extract_mentions`):
  scans body sections for occurrences of every name-variant's ORIGINAL form,
  records `mentions` rows with `extraction_method='heuristic'` and
  `verification_status='candidate'` (NEVER auto-confirmed), captures
  ±120-char context in original orthography. Idempotent (skip existing)
  with `--overwrite` to re-extract. Preserves pre-reform spelling (ъ, ѣ).
- **Toponym candidate table** (`search_toponym` + `toponym` CLI): full §11
  algorithm — strips geo-generics (гора/хребет/перевал/урочище/меер/...) to
  get the toponym core, runs exact+fts+variant+fuzzy for every form,
  returns a de-duplicated candidate table ranked exact>variant>fts>fuzzy
  with per-candidate source URL, snippet, context, confidence, and argument.
  Never auto-merges; candidates are explicitly marked.
- **Mountain-search script** (`scripts/mountain_search.py`): one-command
  end-to-end §11 scenario. Produces a structured report with date-fit,
  region-fit, independence check (2+ excerpts from one document = ONE
  witness), and a cautious verdict (Подтверждено/Вероятно/Возможно/Не
  установлено) + concrete next steps. Verified: honest "Не установлено"
  on absent toponyms, "Подтверждено" with 3 independent witnesses on
  "Дагестан".
- **Research-note CLI** (`note add/list/show/verify`): persist conclusions
  with explicit status (source_fact/interpretation/hypothesis/refuted),
  supporting/contradicting fragments (cited by `sec:<id>` or `doc:<id>`),
  and confidence. `note verify` re-runs the cited searches to confirm every
  fragment still resolves — a reproducibility self-check. Notes can never
  auto-promote from hypothesis to source_fact (no trigger; SKILL forbids it).
- **Works grouping** (`works` CLI): groups documents into logical works by
  URL path prefix (`/Texts/rus<N>/<slug>/` or
  `/Texts/Dokumenty/<region>/<century>/<period>/<slug>/`), so the agent can
  see "this work has 6 parts" and decide which to fetch.
- **Regions listing** (`regions` CLI): prints the known region-catalog slugs.
- **Doctor corpus-empty hint**: if `documents == 0`, doctor prints a
  concrete next-step (`seed_corpus.py` or `crawl`).
- **14 new tests** (test_v02_improvements.py): frameset classification,
  mention extraction (finds/idempotent/overwrite/preserves-spelling/empty),
  toponym table, note add/list/show/verify roundtrip + missing-section
  detection + no-auto-promote, works grouping, doctor empty hint. **67
  passing total** (was 53).

### Changed
- `config.fetch_page_types` now includes `frameset`.
- `ParsedPage` has a new `frames: list[FrameRef]` field.
- `classify()` checks for `<frameset>` BEFORE the bare-.htm branch.
- `extract-mentions` uses the offset-preserving `fold_for_match` for context
  cutting, so snippets map back to original character positions.

## [0.1.0] — 2025-10-27

First working version. Verified against the real vostlit.info structure
(see `docs/SITE_AUDIT.md`).

### Added
- **Collector**: polite `httpx` client (scope guard, delay, retry+backoff,
  page cap, offsite-redirect refusal) + BeautifulSoup parser for every
  verified page type (home, alpha_index, documents_hub, region_catalog,
  itogi_index, document_text `.phtml`, document_text bare `.htm`,
  notes_page, image_gallery, collection_index). Handles `windows-1251`,
  the three colour-coded inline markers (page break `[N]`, chapter `{N}`,
  footnote `<sup>N</sup>`), inline + range-batched notes, `#dann`/`#800040`
  citation blocks, and image galleries.
- **Archive**: content-addressed raw-HTML store (sha256-sharded, idempotent).
- **Database**: SQLite schema (documents, document_versions,
  document_sections, entities, name_variants, mentions, research_notes,
  crawl_log) + 4 FTS5 indexes over normalised text, with explicit sync.
- **Normalisation**: `normalise_search` (NFKC + pre-reform fold + ё fold +
  lower + punct→space), `fold_for_match` (1:1 offset-preserving),
  `strip_geo_generic` (mountain terms incl. Dagestani «меер»), fuzzy via
  `difflib`, `build_fts_query`.
- **Search engine**: exact (Cyrillic-aware CI, ё-preserved), FTS5 ranked,
  name-variant, fuzzy (candidates only), context, hybrid (explainable, exact
  always outranks fuzzy), pluggable semantic (no-op default).
- **Research engine**: `search_documents`, `search_exact`,
  `search_name_variants`, `search_fuzzy`, `search_by_region/author/date`,
  `get_document(_by_url)`, `get_section`, `get_context`,
  `get_document_bibliography`, `find_mentions`, `compare_sources`,
  `export_search_results`.
- **CLI**: `doctor`, `audit-site`, `crawl`, `import-jsonl`, `export`,
  `search`, `search-exact`, `search-variants`, `search-fuzzy`, `document`,
  `section`, `context`, `mentions`, `compare`, `by-region`, `bibliography`,
  `stats`, `rebuild-fts`.
- **Skill**: `SKILL.md` with the mandatory research algorithm + hard
  anti-fabrication rules; `references/` (methodology, source evaluation,
  toponyms, citations); `scripts/` helpers; `examples/research_example.md`
  (the mountain-of-Gumbet scenario, run honestly against the seeded corpus).
- **Docs**: SITE_AUDIT (verified), ARCHITECTURE, DATA_MODEL,
  RESEARCH_WORKFLOW, AGENT_INTEGRATION, TESTING.
- **Tests**: 53 passing (parser, normalize, store, search, CLI, security),
  2 live-site tests skipped by default.
- **Seed corpus**: `scripts/seed_corpus.py` imports 10 verified fixture
  pages + 5 curated Caucasus/Dagestan entities + 4 name variants.

### Known limitations
- Seeded corpus is 10 pages; broader research requires `crawl`.
- `publication_year` heuristic takes the last 4-digit year in the edition
  line (correct for the verified pages, but an approximation).
- ъ/ъ-less mismatch in snippet location is handled via a normalised
  fallback, not a perfect offset map.
- MCP server is not bundled (in-process API + CLI cover all capabilities;
  see AGENT_INTEGRATION.md Mode C).
- Frameset `frame*.htm` pages are discovered but not deeply parsed (the
  audit flagged this as needing verification).
