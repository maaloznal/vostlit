# Changelog

All notable changes to vostlit-research. Dates are Europe/Moscow.

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
