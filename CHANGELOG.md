# Changelog

All notable changes to vostlit-research. Dates are Europe/Moscow.

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
