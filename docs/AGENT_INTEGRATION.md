# Agent Integration

How a code agent connects to this system. Three supported modes, in
increasing order of structure.

## Mode A — CLI (always available, zero extra deps)

The agent shells out to `python3 -m vostlit_research <command>`. Every
command has `--help`, validates arguments, and returns JSON to stdout (or a
human message). The skill's `scripts/` folder provides readable wrappers
(`search.py`, `inspect_document.py`, `compare_sources.py`).

**Security:** the CLI never passes untrusted page content as shell arguments.
The agent must call the documented commands with their own argument
validators; it must not construct arbitrary shell from page text. The
`crawl`/`audit-site` commands are the only network-touching ones and they
are scope-guarded (`allowed_domains`/`allowed_sections`).

## Mode B — In-process Python API

For an agent running in the same Python process (e.g. a tool plugin):

```python
from vostlit_research.config import Config
from vostlit_research.db import Database
from vostlit_research.research.api import ResearchEngine

cfg = Config()
db = Database(cfg.db_path)
eng = ResearchEngine(db)

results = eng.search_documents("Гумбет", region="Дагестан", limit=20)
doc    = eng.get_document(7)
ctx    = eng.get_context(487, before=2, after=2)
mens   = eng.find_mentions("Салатавия")
rep    = eng.compare_sources("Гумбет участвовал", [7, 8])
```

Every method returns plain dicts/lists — trivial to serialise. None returns
fabricated data.

## Mode C — MCP server (optional, not bundled)

The `ResearchEngine` API maps cleanly onto MCP tools. If your agent supports
MCP and the `mcp` Python package is available, a thin server can expose:

| MCP tool | ResearchEngine method |
|----------|----------------------|
| `search_documents` | `search_documents(query, filters)` |
| `search_exact` | `search_exact(phrase, filters)` |
| `search_name_variants` | `search_name_variants(name)` |
| `search_fuzzy` | `search_fuzzy(name, threshold)` |
| `get_document` | `get_document(id)` |
| `get_context` | `get_context(section_id, before, after)` |
| `find_mentions` | `find_mentions(name)` |
| `compare_sources` | `compare_sources(claim, ids)` |
| `get_bibliography` | `get_document_bibliography(id)` |

This is NOT built into v0.1 (the master prompt says: do not add MCP unless
the agent's real tool system requires it and the libs are present). The
in-process API + CLI cover every capability; an MCP adapter is a thin
future addition that does not change the engine.

## Skill registration

The agent-facing skill is registered at
`/home/z/my-project/skills/vostlit-research/SKILL.md` (a symlink to the
canonical `SKILL.md` in the project root, with `references/`, `scripts/`,
`examples/`, `docs/` symlinked alongside). Agents that discover skills from
`skills/<name>/SKILL.md` will pick it up automatically.

## What the agent must NOT do

- Run `crawl` with an unbounded `--limit` (the client caps it, but prefer
  small explicit limits).
- Execute `python3 -m vostlit_research` with arguments built from raw page
  text without validation.
- Treat the local corpus and live-site search as the same thing — the
  corpus is the only thing `search*` reads; live fetches are explicit.
- Modify `data/` files by hand; use the CLI/DB so FTS stays in sync.
