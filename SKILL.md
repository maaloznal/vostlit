---
name: vostlit-research
slug: vostlit-research
version: 0.3.0
description: Reproducible historical research over the vostlit.info source corpus (Caucasus & Dagestan focus). Search, read, compare and cite medieval/early-modern historical sources with verifiable links to the original pages.
metadata: {"clawdbot":{"emoji":"📜","requires":{"bins":["python3"]},"os":["linux","darwin"]}}
---

# Vostlit Research Skill

## When to Use

Use this skill when the user asks about **historical sources** published on
`vostlit.info` — especially materials on the **Caucasus, Dagestan, historical
societies (Гумбет, Салатавия, Авария…), medieval chronicles, or any claim that
must be grounded in a verifiable primary source**. Also use it to **extend the
local corpus** by crawling more of the site.

Do **not** use this skill for: modern news, general encyclopedic questions, or
any answer that does not need a checkable citation. Do **not** answer
historical questions from your own memory when a source check is possible.

## What this skill gives you

A local, reproducible research system with five components (see
`docs/ARCHITECTURE.md`):

1. **Collector** — polite fetcher + verified HTML parser for vostlit.info page
   types (`.phtml` chrome flavor, bare `.htm`, catalogs, notes, galleries).
2. **Archive** — content-addressed local store of raw HTML snapshots.
3. **Search engine** — exact phrase, FTS5 full-text, name-variant, fuzzy,
   context, and (optional, pluggable) semantic search, with explainable
   hybrid ranking.
4. **Research engine** — high-level tools: `search_documents`,
   `get_document`, `get_context`, `find_mentions`, `compare_sources`, …
5. **This Skill** — the algorithm and rules you MUST follow.

Every result keeps a verifiable link to a **document + section + URL**. The
system works **fully offline** once a corpus is imported; the live site is
contacted only on explicit `crawl`/`audit-site` commands.

## Install / one-time setup

```bash
cd <project-root>
python3 -m vostlit_research doctor          # check env, db, FTS5
python3 scripts/seed_corpus.py              # import the 10 verified fixture pages + curated entities
python3 -m vostlit_research stats           # confirm corpus loaded
```

All commands run as `python3 -m vostlit_research <command>` from the project
root (or with `PYTHONPATH=<project-root>`).

## MANDATORY research algorithm

For every research question, follow these steps in order. Skipping a step is a
violation of this skill.

1. **Decompose** the question into entities, dates, geography, and the
   specific claim. Write them down.
2. **List name variants** for each key toponym/person (pre-reform spelling,
   transliterations, OCR variants). Use `search-variants` and `search-fuzzy`.
   For mountains, also try the generic terms: гора, хребет, перевал, вершина,
   высота, урочище, ущелье, and the Dagestani **меер**.
3. **Run exact + full-text searches** (`search-exact`, `search`) for each
   variant and for the core toponym (generic terms stripped via
   `strip_geo_generic` semantics).
4. **Read the context** around every hit with `context <section_id>` — never
   cite a fragment you have not read in context.
5. **Check the source** for each hit: author, document date vs. publication
   date, edition, translator. Use `document <id>` and `bibliography <id>`.
6. **Seek independent corroboration** and **contradictions** across sources
   with `compare "<claim>" <id1> <id2> ...`. Two excerpts that both derive
   from ONE earlier source are NOT independent.
7. **Separate** direct source testimony from your own interpretation.
8. **Answer in the required format** (below). If the corpus has nothing, SAY
   SO and propose a `crawl` to extend it. Never fabricate.

## Hard rules (violations are critical)

- ❌ Never invent a quote, page number, or URL.
- ❌ Never claim a document was "read" if only its title was loaded.
- ❌ Never present a hypothesis as a proven fact.
- ❌ Never treat absence of results as proof an event did not occur.
- ❌ Never merge two toponyms into one entity based on string similarity
  alone — fuzzy matches are CANDIDATES, require context + date + geography
  corroboration.
- ❌ Never treat two excerpts as independent if both trace to one source.
- ❌ Never hide contradictions between sources.
- ❌ Never pass untrusted page content as shell arguments to the CLI — use
  the documented commands and their argument validators.
- ❌ Never output an OCR text as exact transcription without flagging it.
- ❌ Never invent a document date, author, or edition title.

If evidence is insufficient, **say so explicitly**.

## Required answer format

Every substantive answer MUST use this structure:

### Краткий вывод
What was established.

### Найденные источники
Title, author, document date, publication, URL, source type — each a real
record from the corpus.

### Дословные свидетельства
ONLY quotes you actually verified in context, each with `document_id`,
`section_id`, and the vostlit URL. Mark OCR uncertainty.

### Анализ
How the sources support or refute the claim.

### Альтернативы и неопределённость
Other readings; missing evidence.

### Итоговая оценка
One of: **Подтверждено / Вероятно / Возможно / Не установлено**.
Do not use percentages without a calibrated method.

### Следующие поисковые шаги
What to check next (e.g. `crawl --region caucasus --limit 50`, or search a
specific variant).

## CLI quick reference

```bash
python3 -m vostlit_research doctor                       # env + db + FTS5 health
python3 -m vostlit_research stats                        # corpus counts
python3 -m vostlit_research search "<query>"             # hybrid search
python3 -m vostlit_research search-exact "<phrase>"      # exact, preserves spelling
python3 -m vostlit_research search-variants "<name>"     # name-variant dictionary
python3 -m vostlit_research search-fuzzy "<name>"        # candidates only
python3 -m vostlit_research toponym "<name>"             # §11 candidate table (mountain search)
python3 -m vostlit_research by-region Дагестан "<query>" # region filter
python3 -m vostlit_research document <id>                # full document + version
python3 -m vostlit_research section <id>                 # one section
python3 -m vostlit_research context <id> --before 2 --after 2
python3 -m vostlit_research mentions "<name>"            # mentions table + text
python3 -m vostlit_research extract-mentions             # heuristic candidate mentions
python3 -m vostlit_research compare "<claim>" <id1> <id2>
python3 -m vostlit_research bibliography <id>
python3 -m vostlit_research works --min 1                # group docs into logical works
python3 -m vostlit_research regions                      # known region catalog slugs
python3 -m vostlit_research inventory                    # coverage: discovered/parsed/skipped/error/stale
python3 -m vostlit_research resume --limit 25            # resume crawl for discovered/error docs
python3 -m vostlit_research note add --claim "..." --status hypothesis --supporting sec:487
python3 -m vostlit_research note list
python3 -m vostlit_research note show <id>
python3 -m vostlit_research note verify <id>             # reproducibility: cited fragments resolve?
python3 -m vostlit_research audit-site <url>...          # fetch+classify (polite)
python3 -m vostlit_research crawl --region caucasus --limit 25
python3 -m vostlit_research import-jsonl <file>
python3 -m vostlit_research export <out.jsonl>
python3 -m vostlit_research rebuild-fts
```

### Mountain-search scenario (§11) — one-command end-to-end

```bash
python3 scripts/mountain_search.py "гора Джалдари-меер" --region Дагестан --year 1839
```

Runs the full algorithm: decompose → strip geo-generics → expand variants →
exact/fts/variant/fuzzy → candidate table with date-fit, region-fit,
independence check → cautious verdict
(Подтверждено / Вероятно / Возможно / Не установлено) + concrete next steps.
Never asserts identity without ≥2 independent verbatim attestations.

`search`/`search-exact`/`by-region` accept `--region`, `--author`,
`--source-type`, `--date-from`, `--date-to`.

## Extending the corpus

The seeded corpus is only 10 verified pages. To research broader questions,
extend it (politely — the client sleeps `request_delay` seconds between
requests and caps at `max_pages_per_run`):

```bash
# inventory + fetch up to 25 Caucasus-catalog documents
python3 -m vostlit_research crawl --region caucasus --limit 25
# or harvest the alphabetical index for one letter, then fetch
python3 -m vostlit_research crawl --letter G --limit 25
```

The Caucasus catalog (`/Texts/Dokumenty/kavkaz.html`) and the Dagestan
chronicles collection (`/Texts/Dokumenty/Kavkaz/VI/Dag_chron/index.htm`) are
the primary discovery sources for the region (see `docs/SITE_AUDIT.md` §10).

## Reference files

| Topic | File |
|-------|------|
| Research methodology | `references/research-methodology.md` |
| Source evaluation | `references/source-evaluation.md` |
| Historical toponyms & name variants | `references/historical-toponyms.md` |
| Citation rules | `references/citation-rules.md` |
| Worked example (mountain of Gumbet) | `examples/research_example.md` |
| Site structure audit | `docs/SITE_AUDIT.md` |
| Data model | `docs/DATA_MODEL.md` |

## Scope & limits

- The corpus is **local**. If a query returns nothing, the source may simply
  not be imported yet — propose a `crawl`, do not guess.
- The parser is verified against the page types in `docs/SITE_AUDIT.md`. If a
  page type is unknown, `crawl` records it as `skipped` with a warning.
- OCR text is preserved as-is and flagged; it is NOT a verified transcription.
- This skill does NOT publish anything to the internet.
