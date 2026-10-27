# Architecture

## Component map

```
vostlit-research/
├── vostlit_research/                # the Python package
│   ├── __init__.py
│   ├── __main__.py                  # `python -m vostlit_research …`
│   ├── cli.py                       # argparse CLI (all commands)
│   ├── config.py                    # Config (defaults + TOML + env)
│   ├── db.py                        # SQLite + FTS5 bootstrap & sync
│   ├── schema.sql                   # DDL (versioned via schema_version)
│   ├── models.py                    # Pydantic boundary models
│   ├── textnorm.py                  # normalisation, fuzzy, FTS query builder
│   ├── store.py                     # upsert_document (dedup + versioning + FTS sync)
│   ├── archive.py                   # content-addressed raw-HTML store
│   ├── io.py                        # JSONL import/export + entity/variant/note upserts
│   ├── collector/
│   │   ├── http.py                  # polite httpx client (scope guard, delay, retry)
│   │   ├── parser.py                # BeautifulSoup parser per verified page type
│   │   ├── discover.py              # hub/index/catalog -> document URL queue
│   │   └── crawl.py                 # orchestrator: discover->fetch->parse->store
│   ├── search/
│   │   ├── fts.py                   # low-level FTS5 MATCH helpers
│   │   ├── engine.py                # SearchEngine: exact/fts/variants/fuzzy/context/hybrid
│   │   └── semantic.py              # pluggable semantic (no-op default)
│   └── research/
│       └── api.py                   # ResearchEngine: high-level agent tools
├── tests/                           # pytest, fixtures from the real site
├── scripts/                         # seed_corpus.py + skill helper scripts
├── references/ examples/            # Skill reference material
├── docs/                            # this folder
├── config/config.example.toml
├── SKILL.md                         # agent skill (canonical)
└── pyproject.toml
```

## Data flow

```
                 ┌──────── live site (only on explicit crawl/audit-site) ───────┐
                 │                                                              │
   discover.py ──> http.py ──> parser.py ──> store.upsert_document ──> SQLite + FTS5
   (hub/index/     (polite)    (per page      (dedup by canonical_url;        (sync)
    catalog)                    type,           new version on text change)
                               verified
                               selectors)
                                                                                │
   JSONL import ───────────────────────────────────> store.upsert_document ─────┘
   (io.py)

   SearchEngine ──> fts_sections / fts_documents / fts_name_variants + exact LIKE
   ResearchEngine ──> SearchEngine + DB (get_document, context, mentions, compare)
   CLI ──> ResearchEngine / Crawler / io
```

## Key decisions (and why)

- **SQLite + FTS5, no external DB.** The corpus is small-to-medium (thousands
  of documents). FTS5 is built into Python's sqlite3. No Postgres/Elasticsearch.
- **Normalisation is a derived view, never a replacement.** Every original
  string is kept verbatim (`text`, `original_form`); normalised forms live in
  paired columns (`text_lower`) and FTS5 indexes. This is non-negotiable for
  historical fidelity (pre-reform spelling, OCR artifacts).
- **Two parser branches, verified.** `.phtml` (site chrome, `#main`/`#dann`)
  vs bare `.htm` (no chrome, maroon `#800040` citation). Branching on URL
  suffix + presence of `#main`. See `SITE_AUDIT.md`.
- **Three inline numeric markers, colour-coded.** Maroon `[N]` = print page
  break; red `{N}` = source-edition chapter; blue/bare `<sup>N</sup>` =
  footnote ref. The parser records page breaks as their own sections.
- **Explicit FTS sync, not triggers.** `db.reindex_document()` is called after
  every write. Simpler to reason about and test than trigger-based sync over
  normalised columns.
- **Content-addressed HTML archive.** Raw bytes stored by sha256; identical
  pages stored once; re-fetching an unchanged page is a no-op (status
  `unchanged`, no new version).
- **Versioning.** Changed text creates a new `document_versions` row; the old
  version + its sections are retained so a research note can still point at
  the exact text it was made against.
- **Politeness is enforced in the client, not optional.** `HttpClient` checks
  `allowed_domains`/`allowed_sections`, enforces `request_delay`, caps at
  `max_pages_per_run`, retries with backoff+jitter, refuses offsite redirects.
- **Semantic search is pluggable and OFF by default.** No fake vectors. The
  no-op provider contributes zero results to hybrid ranking.
- **Honesty over fluency.** Empty results are reported as empty (with a
  "corpus may be empty" hint), never fabricated. Fuzzy hits are always marked
  `candidate`.

## Dependencies (minimal)

- `httpx` — HTTP
- `beautifulsoup4` + `lxml` — HTML parsing
- `pydantic` v2 — boundary validation
- stdlib: `sqlite3` (with FTS5), `argparse`, `difflib`, `hashlib`, `tomllib`, `re`, `unicodedata`

No LangChain, no Chroma/Qdrant, no always-on cloud API.
