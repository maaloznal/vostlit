# QA VERIFICATION — Independent Verification of P0/P1 Fixes

> **Task ID:** F-qa
> **Agent:** independent-qa
> **Date:** 2025-10-27 (Europe/Moscow)
> **Scope:** independently verify, by running real commands and reading real
> code (not by trusting the worklog), whether the P0/P1 fixes claimed by the
> main agent are actually implemented and working. Produce this document.
> **Constraints respected:** no code modified. Only verification commands run,
> this document written, and the worklog appended.

---

## 1. Method

1. Read all five mandated inputs end-to-end: `docs/UPGRADE_BASELINE.md`,
   `docs/SECURITY_AUDIT.md`, `docs/SCHEMA_AUDIT.md`, `docs/SEARCH_AUDIT.md`,
   `docs/SITE_COVERAGE_AUDIT.md`, and `worklog.md` (Tasks 0, 1-site,
   B-schema, E-security, C-search, A-site).
2. For each of the 14 claims listed in the QA brief, ran the exact command
   specified (or an equivalent that exercises the same code path). Captured
   the real stdout/stderr verbatim.
3. For static claims (presence of a table, value of `__version__`,
   `follow_redirects=False`, etc.), opened the file and cited `file:line`.
4. For runtime claims (RefusedError on offsite URL, section-id stability,
   search filter behaviour), wrote a small Python harness using
   `httpx.MockTransport` (no live traffic to Vostlit) or seeded a temp
   SQLite DB and queried it directly.
5. Did NOT trust any claim in the worklog. The `0`-Task worklog section
   predates the audits; the audit-stage sections (B/E/C/A) pre-date the
   fix pass; no worklog section actually documents the fix pass — so the
   only authoritative source is the code itself.
6. All commands run from `/home/z/my-project/vostlit-research` with
   `PYTHONPATH=.` unless otherwise noted.

The reproduction harnesses are inline in §3 (no external script files
were written, in keeping with the "no code modification" constraint).

---

## 2. Per-claim verification table

| #  | Claim | Status | Evidence (real command output / file:line) |
|----|-------|--------|--------------------------------------------|
| 1  | D-1 redirect leak fixed | **confirmed** | `http.py:86` `follow_redirects=False`; `http.py:241` per-hop `self._check_scope(next_url)`. Runtime: `http._check_scope("https://evil.example.com/")` → `RefusedError: host not allowed: evil.example.com`. MockTransport 302→evil test: `offsite_hits = []  NO LEAK` (no offsite request issued before refusal). |
| 2  | D-2 allowed_sections bypass fixed | **confirmed** | `config.py:35-39` default `allowed_sections = ('/haupt-Dateien/', '/Texts/', '/common/')` (no `/`). Runtime: `_check_scope("https://www.vostlit.info/admin")` → `RefusedError: path not in allowed sections: /admin`; `_check_scope("https://www.vostlit.info/")` → passes. |
| 3  | D-3 raise_for_status on 4xx/5xx; 429/503 trigger `_RetryableStatus` | **confirmed** | No literal `resp.raise_for_status()` call, but an equivalent explicit guard: `http.py:222` `if resp.status_code in (429, 503): raise _RetryableStatus(...)`; `http.py:231` `if resp.status_code >= 400: raise httpx.HTTPStatusError(...)`. Runtime (MockTransport): 429 → `_RetryableStatus` raised internally, retried, then wrapped as `FetchError: fetch failed for …: HTTP 429 for …`; 404 → `FetchError: … HTTP 404 for …`. 4xx/5xx bodies are never returned to the parser. |
| 4  | B-§3.1 section-id stability | **confirmed** | Ran the exact script from the QA brief: output `STABLE 1 1`. Code: `store.py:170-196` — UNCHANGED path skips section rewrite (gated by `existing_sections == 0`); sections now carry a `stable_key` (`schema.sql:87`, `db.py:85-106` backfill). |
| 5  | F1 search_variants respects filter (SQL rows AND FTS hits) | **confirmed** | `engine.py:318` `allowed = _allowed_doc_ids(self.db, filters)` applied to SQL rows (lines 319-331); same filter re-applied to FTS hits at `engine.py:344-351`. Runtime: `search_variants("Дагестан", region="Крым")` → 0 results (Dag-attested variant filtered out); `search_variants("Дагестан", region="Дагестан")` → 1 result; no filter → 1 result. |
| 6  | F2 Cyrillic region filter (lowercase query vs Title-case region) | **partial** | **SearchFilters path works:** `engine.py:140-150` does Python-side `textnorm.fold_for_match` matching. Runtime: `eng.search_exact("Дагестан", SearchFilters(region="дагестан"))` → 1 result ✓. **BUT** `ResearchEngine.search_by_region("дагестан")` (research/api.py:113-117, the no-query listing branch) still uses raw `region LIKE ?` and returns **0** results for the lowercase query (vs 1 for Title-case). `search_by_author` (api.py:123-126) has the same gap. The F2 fix only touched the engine filter path, not the listing API. |
| 7  | F3 date filter semantics (original_creation_date preferred) | **confirmed** | `engine.py:96-109` and `research/api.py:133-148` both use `CAST(substr(COALESCE(d.original_creation_date, d.publication_year, …),1,4) AS INTEGER)`. Runtime: seeded a doc with `original_creation_date="1792"`, `publication_year="2003"`; `search_by_date("1790","1800")` → **1 result** (the 1792 source); `search_exact(...,date_from="1990",date_to="2020")` → **0** results (publication_year 2003 correctly NOT preferred). |
| 8  | Portability — no hardcoded `/home/z/my-project/vostlit-research` in .py | **confirmed** | `Grep` for `/home/z/my-project` in `**/*.py` under the project root → **No files found**. (Matches remain in `docs/*.md` only: SCHEMA_AUDIT.md, SEARCH_AUDIT.md, UPGRADE_BASELINE.md — those are documentation citations, not code.) |
| 9  | Versions consistent (pyproject / __init__ / SKILL = 0.3.0) | **confirmed** | `pyproject.toml:3` `version = "0.3.0"`; `vostlit_research/__init__.py:24` `__version__ = "0.3.0"`; `SKILL.md:4` `version: 0.3.0`. (Caveat: `CHANGELOG.md`'s latest entry is still `[0.2.0]` — no 0.3.0 section. See §3 new defects.) |
| 10 | Test count real | **confirmed** | `python3 -m pytest tests/ -c pyproject.toml` → **77 passed, 2 skipped** (the 2 skipped are `test_integration_live.py` cases gated on `VR_INTEGRATION=1`). Up from the baseline's 67 passed/2 skipped — the delta of +10 matches the new `tests/test_p0_p1_regression.py` file (10 tests, all passing). |
| 11 | Inventory CLI works | **confirmed** | `python3 -m vostlit_research inventory` prints JSON containing `parsed`, `discovered`, `stale_not_checked_30d` (also `total_documents`, `unchanged`, `skipped`, `errored`, `crawl_log_errors`, `documents_by_type`, `unsupported_page_types`, `sections`, `entities`, `name_variants`, `mentions`, `research_notes`). Implementation: `cli.py:502-552`. |
| 12 | Resume CLI exists | **confirmed** | `python3 -m vostlit_research resume --help` exits 0 and prints `usage: python -m vostlit_research resume [-h] [--limit LIMIT] [--force]`. Implementation: `cli.py:555-575` (queues `status IN ('discovered','error')` docs and re-crawls them). |
| 13 | `schema_version == 2` | **confirmed** | `python3 -m vostlit_research doctor` reports `schema_version: 2`. Direct DB probe: `SELECT * FROM schema_version` → `(2, '2026-10-27T15:48:07Z')`. Constant: `db.py:25` `SCHEMA_VERSION = 2`. |
| 14 | `document_relations` + `research_note_fragments` tables exist | **confirmed** | `SELECT name FROM sqlite_master WHERE type='table'` includes both `document_relations` and `research_note_fragments` (plus `documents`, `document_versions`, `document_sections`, `entities`, `name_variants`, `mentions`, `research_notes`, `crawl_log`, `schema_version`, and the four `fts_*` virtual tables). DDL: `schema.sql:182-191` (research_note_fragments), `schema.sql:201-214` (document_relations). |

**Tally:** 12 confirmed, 1 partial (F2), 1 confirmed-with-caveat (D-3 —
uses an explicit status-code check rather than a literal
`resp.raise_for_status()` call; behaviour is equivalent).

---

## 3. NEW defects / gaps that the other agents missed

These were found during independent verification, not from the worklog.

### N1 — `ResearchEngine.search_by_region` / `search_by_author` listing branches still F2-broken

**Severity:** HIGH (silent wrong results — same defect class as F2).

**Evidence.** `research/api.py:113-117`:

```python
rows = self.db.conn.execute(
    "SELECT id, canonical_url, title, author, region, publication_year, page_type FROM documents WHERE region LIKE ? ORDER BY title LIMIT ?",
    (f"%{region}%", limit),
).fetchall()
```

`research/api.py:123-126` (search_by_author) has the same shape.

`LIKE` in SQLite is case-insensitive for ASCII only. For Cyrillic,
`region='Дагестан'` does **not** match the pattern `%дагестан%`.

**Reproduction (real output):**

```
search_by_region("дагестан") lowercase results: 0
search_by_region("Дагестан") Title-case results: 1
```

The F2 fix only patched the `SearchFilters` path (used by `search_exact`,
`search`, `search_variants`, `search_hybrid`); the no-query listing
branch of `search_by_region` and `search_by_author` was missed.

**Suggested fix:** route both listing branches through `_allowed_doc_ids`
or apply `textnorm.fold_for_match` to both sides in Python (same pattern
as `engine.py:140-150`).

---

### N2 — `search_fuzzy` still ignores its `filters` parameter

**Severity:** MEDIUM (the audit's F1 named both `search_variants` and
`search_fuzzy`; only `search_variants` was fixed).

**Evidence.** `engine.py:387` signature accepts `filters: SearchFilters |
None = None` but the function body (lines 388-444) never references
`filters` and never calls `_allowed_doc_ids`. All fuzzy results carry
`document_id=0` (dictionary-only candidates), so they bypass any
document-level filter.

This is partly defensible — fuzzy results are explicitly CANDIDATES, not
attested-in-document matches — but the contract is misleading: a caller
who passes `SearchFilters(region="Дагестан")` to `search_fuzzy` will
receive candidates whose evidence (if any) is in unrelated regions.
`search_toponym` (engine.py:554) does pass `filters` down to
`search_fuzzy`, where the parameter is silently dropped.

**Suggested fix:** either (a) drop the `filters` parameter from
`search_fuzzy` and document that fuzzy results are unfiltered by design,
or (b) actually filter — for variants with `evidence_section_id`, drop
those whose evidence document is excluded; for entity-canonical-name
fuzzy hits, keep them (no document linkage).

---

### N3 — `CHANGELOG.md` missing the 0.3.0 entry

**Severity:** LOW (documentation drift).

**Evidence.** `head -7 CHANGELOG.md`:

```
# Changelog
All notable changes to vostlit-research. Dates are Europe/Moscow.
## [0.2.0] — 2025-10-27
```

`pyproject.toml`, `__init__.py`, and `SKILL.md` all say `0.3.0`, but the
changelog stops at `0.2.0`. A user reading the changelog has no way to
know that the security/reproducibility/search fixes were shipped.

---

### N4 — SITE_COVERAGE_AUDIT's three P0 content-loss bugs remain unaddressed

**Severity:** HIGH (the system cannot actually ingest large portions of
the target corpus, even though the per-page parser handles them).

**Evidence.** Subagent A-site's `docs/SITE_COVERAGE_AUDIT.md` §10 listed
3 P0 coverage bugs. Verification against the current code:

1. **`discover._is_doc_url` still requires `/texts/` in path** —
   `discover.py:60` `if "/texts/" not in path: return False`. So
   `/common/lib_uk.phtml`, `/common/tables.phtml`, `/common/itogi*.phtml`,
   `/bin/find_doc.php`, `/Repertorium/index.htm`, `/MGH/index.htm`,
   `/MPH/index.htm` are all silently dropped by discovery. **NOT FIXED.**
2. **`chrono.phtml` pages yield 0 sections** — `parser.py` still skips
   `<p>` inside `<table>` (the documented cause). No `chrono` page type
   was added. **NOT FIXED.**
3. **`region_catalog` and `alpha_index` are NOT in `fetch_page_types`** —
   `config.py:69-76` lists `document_text, document_excerpt, notes_page,
   image_gallery, collection_index, frameset` only. `region_catalog` and
   `alpha_index` are still skipped by the real crawler, so
   `kavkaz.html`'s 349 region-catalog entries and the alpha index's 710+
   author/work titles are not indexed by `crawl`. **NOT FIXED.**

(The 10 seeded docs in `data/vostlit.db` were force-imported by
`scripts/seed_corpus.py`; the discover→crawl pipeline is still
UNTESTED end-to-end against the persistent DB — crawl_log is empty.)

This is outside the 14 QA-brief claims but is the single biggest
readiness gap: the system can search and reason over a hand-seeded
corpus, but cannot actually build that corpus itself for the Caucasus
region beyond the 10 fixtures.

---

### N5 — `db.py:_now()` uses deprecated `datetime.utcnow()`

**Severity:** LOW (deprecation warning in Python 3.12+; will break in a
future Python release).

**Evidence.** `db.py:31`: `return datetime.utcnow().isoformat(timespec="seconds") + "Z"`.

`datetime.utcnow()` was deprecated in Python 3.12 (PEP 587 / DeprecationWarning).
Use `datetime.now(timezone.utc).replace(tzinfo=None)` instead.

---

## 4. Overall readiness verdict

> **"working prototype with significant limitations"**

---

## 5. Justification (with verified evidence)

**Why NOT "has blocking defects":** The three CRITICAL security defects
identified in `SECURITY_AUDIT.md` (D-1 redirect leak, D-2 allowed_sections
bypass, D-3 silent-accept of 4xx/5xx) are all genuinely fixed and
runtime-verified (claims 1-3 above). The single CRITICAL schema defect
(B-§3.1 section-id instability on re-parse) is also genuinely fixed
(claim 4: `STABLE 1 1`). With these fixed, the crawler can no longer be
trivially pivoted to attack arbitrary hosts, cannot be coerced into
fetching `/admin`/`/.env`, and will not silently store 429/500 bodies as
document text. Re-importing the same URL no longer orphans
`mentions.section_id` / `name_variants.evidence_section_id` / research-note
fragments. These were the only "blocking" issues in the audit; they are
closed.

**Why NOT "ready for research use":** Two reasons:

1. **Site coverage is still broken in the same 3 P0 ways Subagent A-site
   flagged** (N4 above). The crawler cannot actually discover or ingest
   `/common/*.phtml` (itogi, lib_uk, tables, karten), `/bin/find_doc.php`,
   `/Repertorium/`, `/MGH/`, `/MPH/`; cannot parse `chrono.phtml`
   timelines; and is configured to skip `region_catalog` and `alpha_index`
   pages entirely. For a research tool whose purpose is "reproducible
   research over the vostlit.info source corpus (Caucasus & Dagestan
   focus)", the fact that `kavkaz.html`'s 349 Caucasus-catalog entries
   cannot be indexed by the crawler is a fundamental readiness gap.
2. **F2 is only partially fixed (N1).** A historian searching
   `by-region "дагестан"` (lowercase) silently gets 0 results. This is
   the exact defect class the F2 fix was supposed to close; the engine
   filter path was fixed, the listing-API path was missed. For a
   Russian-language research tool this is a real correctness bug.

**Why NOT "incomplete implementation":** The 10 new P0/P1 regression
tests (`tests/test_p0_p1_regression.py`) all pass. The 67 prior tests
still pass (77/77 total, 2 skipped live). The schema migration to v2
runs cleanly on a fresh DB and on the persistent `data/vostlit.db`
(schema_version=2 verified). The new `inventory` and `resume` CLIs work.
The 14 specific claims are 12 confirmed + 1 partial + 1
confirmed-with-caveat — i.e. the main agent's fix pass did real work and
delivered what it claimed, with two specific misses (N1, N2) and three
out-of-scope-but-critical gaps (N4).

**Net assessment:** The P0/P1 security + reproducibility + search-filter
fixes are real and verifiable. The system is safe to develop against and
safe to run against a hand-seeded corpus (which is what the test suite
does). It is **not** yet ready to be the primary research tool for a
working historian, because the discovery pipeline cannot actually build
that corpus from the live site beyond the 10 hand-seeded documents, and
the listing-API search methods still have a Cyrillic case-sensitivity
bug. Closing N1 (small, ~10 lines) and N4 (medium, the three
site-coverage P0s) would move this to "ready for research use"; N2, N3,
N5 are clean-up.
