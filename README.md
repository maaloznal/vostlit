# vostlit-research

A reproducible, local research system over the historical sources published at
[**vostlit.info**](https://www.vostlit.info/) — *Восточная литература*, a
library of medieval and early-modern historical sources of the East and West,
with a focus on the **Caucasus and Dagestan**.

It is **not** a chatbot that answers from model memory, and **not** a dumb
site scraper. It is a research system that lets an AI agent (or a human)
**search, read, analyse and compare** historical sources with **verifiable
links back to the original pages**.

> Every historical conclusion must keep a verifiable link to a specific
> fragment of a specific source.

## What it does

- **Collector** — a *polite* HTTP fetcher + an HTML parser whose selectors are
  **verified against real pages** (see [`docs/SITE_AUDIT.md`](docs/SITE_AUDIT.md)).
  Handles the site's two document flavors (`.phtml` with site chrome, bare
  `.htm`), its `windows-1251` encoding, page-break/footnote markers, citation
  blocks, image galleries, and collection indexes.
- **Archive** — a content-addressed local store of raw HTML snapshots.
- **Search engine** — exact phrase (preserves original spelling & ё), FTS5
  full-text (ё/pre-reform-insensitive), name-variant dictionary, fuzzy
  candidates, context filters, and explainable hybrid ranking. Semantic
  search is pluggable and **off by default** (no fake vectors).
- **Research engine** — `get_document`, `get_context`, `find_mentions`,
  `compare_sources`, bibliography, …
- **Agent Skill** — a documented research algorithm with hard rules against
  fabrication (see [`SKILL.md`](SKILL.md)).

## Quick start

```bash
cd <project-root>

# 1. health check (env, db, FTS5)
python3 -m vostlit_research doctor

# 2. load the 10 verified fixture pages + curated Caucasus/Dagestan entities
python3 scripts/seed_corpus.py

# 3. search
python3 -m vostlit_research search "Дагестан"
python3 -m vostlit_research search-exact "дагестанск"
python3 -m vostlit_research by-region Дагестан

# 4. read a document in context
python3 -m vostlit_research document 7
python3 -m vostlit_research context 487 --before 1 --after 1
```

## Extending the corpus (live site, polite)

```bash
# inventory + fetch up to 25 Caucasus-catalog documents
python3 -m vostlit_research crawl --region caucasus --limit 25
# harvest one letter of the alphabetical author index
python3 -m vostlit_research crawl --letter G --limit 25
# only build the inventory, no text fetch
python3 -m vostlit_research crawl --region caucasus --discover-only
```

The client sleeps `request_delay` (default 3 s) between requests, caps at
`max_pages_per_run` (25), retries with backoff, and refuses offsite
redirects. Re-running skips already-parsed documents.

## CLI reference

```
doctor            health check (env, db, FTS5)
stats             corpus counts
search <q>        hybrid search (exact+fts+variants+fuzzy)
search-exact <p>  exact phrase (preserves spelling)
search-variants   name-variant dictionary
search-fuzzy      candidates only
by-region <r> [q] region-filtered
document <id>     full document + current version
section <id>      one section
context <id>      section + surrounding context
mentions <name>   mentions table + text search
compare <claim> <ids...>
bibliography <id>
audit-site <urls...>   fetch+classify (polite)
crawl [--region R] [--letter L] [--seed U] [--limit N] [--force] [--discover-only]
import-jsonl <file>
export <out.jsonl> [--no-sections]
rebuild-fts
```

`search`/`search-exact`/`by-region` accept `--region`, `--author`,
`--source-type`, `--date-from`, `--date-to`.

## Configuration

Defaults live in `vostlit_research/config.py`. Override via
`config/config.toml` (copy from `config/config.example.toml`) or environment
variables prefixed `VOSTLIT_` (e.g. `VOSTLIT_DB_PATH`,
`VOSTLIT_REQUEST_DELAY`, `VOSTLIT_MAX_PAGES_PER_RUN`). No secrets are
required.

## Documentation

| Doc | Purpose |
|------|---------|
| [`SKILL.md`](SKILL.md) | the agent skill (algorithm + rules) |
| [`docs/SITE_AUDIT.md`](docs/SITE_AUDIT.md) | verified structure of vostlit.info |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | component map & decisions |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | schema |
| [`docs/RESEARCH_WORKFLOW.md`](docs/RESEARCH_WORKFLOW.md) | step-by-step method |
| [`docs/AGENT_INTEGRATION.md`](docs/AGENT_INTEGRATION.md) | CLI / API / MCP |
| [`docs/TESTING.md`](docs/TESTING.md) | test suite & limits |
| [`examples/research_example.md`](examples/research_example.md) | the mountain-of-Gumbet scenario |
| [`references/`](references/) | methodology, source evaluation, toponyms, citations |

## Tests

```bash
python3 -m pytest tests/ -c pyproject.toml          # 53 passed, 2 skipped
VR_INTEGRATION=1 python3 -m pytest tests/test_integration_live.py -s   # live site
```

## Dependencies

`httpx`, `beautifulsoup4` + `lxml`, `pydantic` v2, and the Python stdlib
(`sqlite3` with FTS5, `argparse`, `difflib`, `tomllib`). No external DB, no
vector store, no always-on cloud API. Python ≥ 3.11.

## Provenance & rights

The corpus reproduces texts from vostlit.info under that site's terms. Each
document keeps its `canonical_url`, its edition citation
(`publication_title`), and the © lines from the source page. The local
archive and fixtures are for **personal research only** and must not be
redistributed. The collector respects `allowed_domains`/`allowed_sections`
and uses polite delays; it does not bypass auth/CAPTCHA/paywall.

## Status (v0.1.0)

Working MVP: collector, archive, FTS5 search, research engine, CLI, skill,
tests — all verified against real fixtures. The seeded corpus is 10 pages;
extend it with `crawl`. See [`CHANGELOG.md`](CHANGELOG.md).
