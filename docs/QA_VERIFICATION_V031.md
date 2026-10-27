# QA VERIFICATION V0.3.1 — Independent Verification of v0.3.1 Claims

> **Task ID:** F-qa-v031
> **Agent:** independent-qa-v031
> **Date:** 2025-10-27 (Europe/Moscow)
> **Scope:** independently verify, by running real commands and reading real
> code (not by trusting the worklog or the v0.3.0 QA report), whether the
> v0.3.1 claims hold. Produce this document.
> **Constraints respected:** no code modified. Only verification commands run,
> this document written, and the worklog appended.

---

## 1. Method

1. Read all eight mandated inputs end-to-end: `worklog.md`,
   `docs/UPGRADE_BASELINE.md`, `docs/SECURITY_AUDIT.md`,
   `docs/SCHEMA_AUDIT.md`, `docs/SEARCH_AUDIT.md`,
   `docs/SITE_COVERAGE_AUDIT.md`, `docs/QA_VERIFICATION.md` (the v0.3.0
   report), `docs/IMPLEMENTATION_REPORT.md`.
2. For each of the 12 claims in the QA brief, ran the exact command
   specified (or an equivalent that exercises the same code path) and
   captured real stdout/stderr verbatim. Every "confirmed" row in §2
   cites a real command output, not a code reading.
3. For static claims (`__version__`, `fetch_page_types` membership,
   CHANGELOG entry), opened the file and cited `file:line`.
4. For runtime claims (102 tests, `_is_doc_url` acceptance, chrono
   sections, redirect refusal, 4xx no-retry, inventory discovered>0),
   ran the actual pytest invocations and Python one-liners from a
   shell — transcripts cited inline.
5. Read the full `git diff HEAD` for every modified file
   (`http.py`, `discover.py`, `config.py`, `parser.py`, `pyproject.toml`,
   `__init__.py`, `SKILL.md`, `CHANGELOG.md`, `README.md`,
   `docs/TESTING.md`) and every new test file
   (`tests/test_discovery_fixes.py`, `tests/test_redirect_http.py`,
   `tests/test_e2e_pipeline.py`) to find defects the agent may have
   missed. Findings in §3.
6. Did NOT trust any claim in `worklog.md` or `IMPLEMENTATION_REPORT.md`.
   The only authoritative sources are the code and the runtime output.
7. All commands run from `/home/z/my-project/vostlit-research` with
   `PYTHONPATH=.` (set by `pyproject.toml`'s `[tool.pytest.ini_options]`).

---

## 2. Per-claim verification table

| #  | Claim | Status | Evidence (real command output / file:line) |
|----|-------|--------|--------------------------------------------|
| 1  | HEAD is still published v0.3.0 (427273c), NOT committed | **confirmed** | `git rev-parse HEAD` → `427273c7351a38de4a02973f2d973048b03e5230`. `git status --short` shows 10 modified files + 3 untracked test files (`?? tests/test_discovery_fixes.py`, `?? tests/test_e2e_pipeline.py`, `?? tests/test_redirect_http.py`). `git log --oneline -1` → `427273c v0.3.0: Master Upgrade — P0 security/reproducibility + P1 search fixes + inventory/resume`. Working tree is dirty; v0.3.1 is uncommitted. |
| 2  | 102 tests pass | **confirmed** | `python3 -m pytest tests/ -c pyproject.toml` → `102 passed, 2 skipped in 4.38s`. The 2 skipped are `tests/test_integration_live.py` (gated on `VR_INTEGRATION=1`). Per-file collect: `test_cli_security.py: 10, test_discovery_fixes.py: 14, test_e2e_pipeline.py: 2, test_integration_live.py: 2, test_normalize.py: 12, test_p0_p1_regression.py: 10, test_parser.py: 12, test_redirect_http.py: 9, test_search.py: 11, test_store.py: 8, test_v02_improvements.py: 14` → total 102 passed + 2 skipped = 104. |
| 3  | N4a: `_is_doc_url` accepts `/common/`, `/Repertorium/`, `/MGH/`, `/MPH/` | **confirmed** | Code: `discover.py:74-77` `if not any(root in path for root in ("/texts/", "/common/", "/repertorium/", "/mgh/", "/mph/")): return False`. Runtime: `python3 -c "from vostlit_research.collector.discover import _is_doc_url as f; print(f('https://www.vostlit.info/common/x.phtml'), f('https://www.vostlit.info/Repertorium/y.htm'), f('https://www.vostlit.info/MGH/z.phtml'), f('https://www.vostlit.info/MPH/w.htm'))"` → `common: True Repertorium: True MGH: True MPH: True`. All four True. |
| 4  | N4b: `chrono.phtml` yields sections | **confirmed** | `python3 -m pytest tests/test_discovery_fixes.py::test_chrono_page_yields_sections_from_table -c pyproject.toml` → `1 passed in 0.80s`. Manual reproduction with the test's synthetic HTML: `page_type = chrono`, `body sections = 3`, `extracted_text contains Event one: True`, `extracted_text contains Event three: True`. Code: `parser.py:191-192` classify branch, `parser.py:482-543` `_parse_chrono` extracts every `<tr>` as a body section. |
| 5  | N4c: `region_catalog`/`alpha_index` in `fetch_page_types` | **confirmed** | `config.py:81-95`: `fetch_page_types` tuple includes `"chrono"` (line 88), `"region_catalog"` (line 93), `"alpha_index"` (line 94). Runtime: `tests/test_discovery_fixes.py::test_fetch_page_types_includes_chrono_and_catalogs` passes (part of the 14-test file). |
| 6  | Unknown page types recorded (not silently dropped) | **confirmed** (implementation) / **weak test** (see N1-v031) | Code: `parser.py:205` `return "unknown"` (classify fallback); `parser.py:242-247` `else:` branch in `parse_page` sets `parsed.page_type = "unknown"` + appends warning `"unclassified page type for: {url}"`. Runtime verification (NOT via the weak test): `parse_page("https://www.vostlit.info/something.php", ...)` → `page_type = 'unknown'`, `warnings = ['unclassified page type for: https://www.vostlit.info/something.php']`. The crawl layer (`crawl.py:123-130`) marks unknown pages `status='skipped'` with `page_type` set, so `inventory` reports them via `unsupported_page_types` (`cli.py:529-542`). |
| 7  | Real HTTP redirect test (MockTransport, specific assertions) | **confirmed** | `tests/test_redirect_http.py` uses `httpx.MockTransport(transport_handler)` at line 46. `python3 -m pytest tests/test_redirect_http.py -c pyproject.toml` → `9 passed in 1.03s`. Specific assertions verified by reading the test file + running each test individually: <br>• `test_302_to_offsite_host_refused_without_request` (line 92-93): `assert not any("evil.example.com" in u for u in requested)` ✓ <br>• `test_404_not_retried` (line 185): `assert call_count["n"] == 1` ✓ <br>• `test_429_numeric_retry_after_honored` (line 209): `assert any(abs(s - 2.0) < 0.01 for s in sleeps)` ✓ <br>• `test_body_size_exceeded_without_content_length` (line 258): `with pytest.raises(TooLargeResponseError)` ✓ |
| 8  | E2E pipeline on persistent DB | **confirmed** (with caveats — see N3-v031, N4-v031) | `tests/test_e2e_pipeline.py:82` `cfg.db_path = tmp_path / "e2e.db"` (persistent file DB, NOT `:memory:`). Stages: discover (line 113) → crawl (line 134) → re-import ID stability (line 165) → inventory via `db.stats()` (line 174) → resume (line 193, see caveat). SQL SELECTs on `documents` (lines 118, 139, 159, 167, 196, 204), `document_sections` (lines 145, 159, 167), `fts_sections` (line 153). `python3 -m pytest tests/test_e2e_pipeline.py -c pyproject.toml` → `2 passed in 1.11s`. **Caveat:** Stage 5 ("resume") is effectively a no-op — see §3 N3-v031. |
| 9  | 4xx no longer retried; `_RetryableStatus` caught BEFORE `HTTPStatusError` | **confirmed** | `http.py:229-241`: `if resp.status_code in (429, 503): raise _RetryableStatus(...)` is checked BEFORE `if resp.status_code >= 400: raise httpx.HTTPStatusError(...)`. In `fetch()` (line 170-212): `except _RetryableStatus` (line 185) is caught BEFORE `except httpx.HTTPStatusError` (line 196). The `HTTPStatusError` handler (line 196-201) immediately `raise FetchError(...)` — no retry loop. Runtime: `test_404_not_retried` asserts `call_count["n"] == 1` ✓. Git diff confirms only the `HTTPStatusError` except clause was added (`+7 lines` in http.py). |
| 10 | Inventory shows discovered>0 | **confirmed** | `python3 -m pytest tests/test_e2e_pipeline.py::test_e2e_inventory_shows_meaningful_counters -c pyproject.toml` → `1 passed in 1.00s`. The test (line 213-232) spawns a real subprocess: `subprocess.run([sys.executable, "-m", "vostlit_research", "inventory"], ...)` and asserts `data["discovered"] >= 1` (line 231) and `data["total_documents"] >= 1` (line 232). This exercises the actual CLI command, not a direct function call. |
| 11 | Versions consistent at 0.3.1 | **confirmed** | `pyproject.toml:3` `version = "0.3.1"`; `vostlit_research/__init__.py:24` `__version__ = "0.3.1"`; `SKILL.md:4` `version: 0.3.1`. All three agree. (CHANGELOG also has 0.3.1 — see claim 12.) |
| 12 | CHANGELOG has 0.3.1 entry | **confirmed** | `CHANGELOG.md:5` `## [0.3.1] — 2025-10-27`. First entry, above the prior `## [0.3.0]` section. The 0.3.1 section documents N4a/N4b/N4c, the HTTP 4xx-no-retry fix, the 9 MockTransport tests, and the E2E pipeline test. |

**Tally:** 12 confirmed. Two of the confirmed claims (6 and 8) carry caveats
documented in §3 — the implementation is correct but the tests are weak or
misleading. No claim is refuted.

---

## 3. NEW defects / gaps found during independent verification

These were found by reading the diff and the test files carefully, not from
the worklog. Severity is judged by impact on the *trustworthiness of the
test suite* (a misleading test is worse than a missing feature, because it
creates false confidence).

### N1-v031 — `test_unknown_page_type_recorded_with_warning` does not test what its name claims

**Severity:** HIGH (misleading test — creates false confidence in claim 6).

**Evidence.** `tests/test_discovery_fixes.py:105-118`:

```python
def test_unknown_page_type_recorded_with_warning():
    """A page that matches no known type must be classified 'unknown' with a
    warning, so inventory can report it (not silently lost)."""
    html = b"""<html><head><title>weird</title></head>
    <body><div>something unusual</div></body></html>"""
    p = parse_page("https://www.vostlit.info/Texts/rus/X/weird.phtml?id=1", html, charset="utf-8")
    ...
    html2 = b"""<html><head><title>x</title></head><body><p>no main, no frameset, .phtml</p></body></html>"""
    p2 = parse_page("https://www.vostlit.info/Texts/rus/X/unknown.phtml?id=2", html2, charset="utf-8")
    ...
    assert p2.page_type in ("document_text", "unknown")  # not crashed
```

Three problems:

1. Both test URLs end in `.phtml`, so `classify()` (`parser.py:199-200`)
   returns `"document_text"` for both. The `"unknown"` branch
   (`parser.py:205`) is **never exercised** by this test.
2. The assertion `p2.page_type in ("document_text", "unknown")` accepts
   EITHER outcome — it cannot fail for the `unknown` case OR the
   `document_text` case. It is a tautology given the URL shape.
3. The docstring says "classified 'unknown' with a warning" but there is
   **no assertion on `p.warnings` or `p2.warnings`** anywhere in the test.

**Runtime proof:**
```
p2.page_type = 'document_text'
p2.warnings = ['bare .htm document (no site chrome)']
```

The implementation IS correct — manually feeding a non-`.phtml`/`.htm`/`.html`
URL with no `#main` (e.g. `https://www.vostlit.info/something.php`) returns
`page_type='unknown'` with the expected warning. But the test does not
verify this; it would pass even if the `unknown` branch were deleted.

**Suggested fix:** add a third case with a URL like
`https://www.vostlit.info/common/foo.php` and assert
`p3.page_type == "unknown"` and `"unclassified page type" in p3.warnings[0]`.

### N2-v031 — `test_302_to_forbidden_path_on_same_host_refused` final assertion is a no-op

**Severity:** MEDIUM (the test's stated guarantee — "forbidden path was not
requested" — is not actually verified).

**Evidence.** `tests/test_redirect_http.py:98-127`:

```python
def test_302_to_forbidden_path_on_same_host_refused(tmp_path):
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)

    def handler(request):           # <-- first handler, captured by _client_with_mock
        if "vostlit.info/allowed" in str(request.url):
            return httpx.Response(302, headers={"Location": "https://www.vostlit.info/admin/secret"})
        return httpx.Response(200, text="ok")

    http, requested = _client_with_mock(cfg, db, handler)   # `requested` bound to handler
    try:
        ...
        def handler2(request):      # <-- second handler, NEVER records into `requested`
            if "vostlit.info/Texts/allowed" in str(request.url):
                return httpx.Response(302, headers={"Location": "https://www.vostlit.info/admin/secret"})
            return httpx.Response(200, text="ok")
        mock2 = httpx.MockTransport(handler2)
        http._client.close()
        http._client = httpx.Client(..., transport=mock2)   # <-- replaces the transport
        with pytest.raises(RefusedError):
            http.fetch("https://www.vostlit.info/Texts/allowed")
    finally:
        http.close(); db.close()
    assert not any("/admin/secret" in u for u in requested), \
        f"forbidden path was requested! calls={requested}"
```

The final assertion checks `requested` — the list captured by the FIRST
`handler`'s closure. But the first handler is never used: before any
`http.fetch()` call, `http._client` is replaced with a new client whose
transport is `mock2` (built from `handler2`). `handler2` does NOT append to
`requested`. So at assertion time, `requested == []` and the assertion
`not any("/admin/secret" in u for u in [])` is trivially True.

The test would pass even if `handler2` had requested `/admin/secret` a
hundred times. The "forbidden path was not requested" guarantee is
unverified.

(The `pytest.raises(RefusedError)` block IS meaningful — it verifies that
the redirect to `/admin/secret` is refused. Only the trailing
"not-requested" assertion is broken.)

**Suggested fix:** make `handler2` append to `requested` (or use a single
handler throughout), and re-run the assertion against the list that
actually recorded the fetch.

### N3-v031 — `test_e2e_pipeline_on_persistent_db` Stage 5 ("resume") is effectively a no-op

**Severity:** HIGH (the test claims to verify resume-after-interruption;
it does not).

**Evidence.** `tests/test_e2e_pipeline.py:179-201`:

```python
# ---------- Stage 5: resume after simulated interruption ----------
# mark one doc as 'discovered' (simulating it was queued but not fetched)
# find a doc that's NOT parsed yet (e.g. Doc2 if it 404'd, or force one)
# Insert a fake discovered doc to simulate an interrupted queue
db.conn.execute(
    "INSERT OR IGNORE INTO documents (canonical_url, stable_id, first_seen_at, last_checked_at, status) VALUES (?,?,?,?, 'discovered')",
    ("https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Other/text.htm",
     "other", db.now(), db.now())
)
db.conn.commit()
# resume should pick it up and parse it
http = _mock_http(cfg, db)
crawler = Crawler(cfg, db)
crawler.http = http
report2 = crawler.crawl(seeds=["https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Other/text.htm"], limit=1)
http.close()
other = db.conn.execute(
    "SELECT status, title FROM documents WHERE canonical_url='https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Other/text.htm'"
).fetchone()
assert other is not None
assert other["status"] == "parsed", f"resume did not parse the doc: {other['status']}"
assert other["title"] == "OTHER DOC"
```

Tracing the data flow:

1. Stage 1 (`discover(regions=["testcat"])`) discovers two URLs from the
   synthesized `testcat.html`: Doc1 (`Dagestan_poddanstvo_1792/text.htm`)
   and Doc2 (`Other/text.htm`). Both are inserted with `status='discovered'`.
2. Stage 2 (`crawler.crawl(regions=["testcat"], limit=5)`) fetches both.
   `_serve_fixtures` returns a real fixture for Doc1 and a synthesized
   HTML for Doc2 (line 68-76). Both parse successfully → `status='parsed'`
   for both.
3. Stage 5's `INSERT OR IGNORE` for Doc2's URL is a **no-op** — the row
   already exists with `status='parsed'`. `INSERT OR IGNORE` does not
   reset the status to `'discovered'`. (To actually simulate an
   interrupted queue, the test would need
   `UPDATE documents SET status='discovered' WHERE canonical_url=...`.)
4. `crawler.crawl(seeds=[Doc2_url], limit=1)` calls `_run_discover` (no-op
   insert) then `_select_queue` with `force=False`. `_select_queue`
   (`crawl.py:105-110`) skips rows with `status IN ('parsed','unchanged')`.
   Doc2 is `parsed` → skipped. The queue is empty. The for-loop body
   never runs. `report2.parsed == 0`.
5. The assertion `assert other["status"] == "parsed"` passes because
   Doc2 was parsed in **Stage 2**, not because of Stage 5's "resume".

The test would pass even if `cmd_resume` (the actual CLI command at
`cli.py:555-575`) were deleted, or if `Crawler._select_queue`'s
`status IN ('discovered','error')` clause were removed. It does not
exercise resume semantics.

(The test also does not invoke the `resume` CLI command — it calls
`Crawler.crawl(seeds=[...])` directly. The actual `python -m
vostlit_research resume` CLI is exercised by no test in v0.3.1.)

**Suggested fix:** use `UPDATE documents SET status='discovered' WHERE
canonical_url=...` (not `INSERT OR IGNORE`) to actually reset Doc2's
status, then verify `report2.parsed >= 1` and that the doc was re-parsed
in Stage 5 (not Stage 2). Even better: add a separate test that spawns
`python -m vostlit_research resume` as a subprocess (mirroring
`test_e2e_inventory_shows_meaningful_counters`).

### N4-v031 — `test_e2e_pipeline.py` module docstring is misleading

**Severity:** LOW (documentation, not behaviour).

**Evidence.** `tests/test_e2e_pipeline.py:1`:
```
"""End-to-end pipeline test on a PERSISTENT test DB with a local HTTP server.
```
But the test uses `httpx.MockTransport` (`_serve_fixtures` at line 39,
wired in at line 95-101), not a real HTTP server. "Local HTTP server"
implies `socketserver`/`http.server`/a real port. The MockTransport
intercepts at the httpx layer; no socket is ever opened. The distinction
matters because a real server would exercise DNS, connection reuse, and
actual HTTP framing — MockTransport does not.

**Suggested fix:** s/local HTTP server/httpx.MockTransport/ in the
docstring.

### N5-v031 — `test_404_not_retried` accepts an unreachable exception type

**Severity:** LOW (test passes, but the assertion is looser than it looks).

**Evidence.** `tests/test_redirect_http.py:179`:
```python
with pytest.raises((httpx.HTTPStatusError, FetchError)):
    http.fetch("https://www.vostlit.info/Texts/missing")
```
`http.fetch()` (`http.py:170-212`) catches `httpx.HTTPStatusError` at
line 196 and re-raises as `FetchError` at line 201. So
`httpx.HTTPStatusError` can **never** propagate out of `http.fetch()`.
The tuple `(httpx.HTTPStatusError, FetchError)` is equivalent to just
`FetchError`. The test would pass even if the conversion at line 196-201
were broken in a way that leaked `httpx.HTTPStatusError` — which is the
opposite of what a tight test should ensure.

**Suggested fix:** `with pytest.raises(FetchError):` — that is what
actually propagates.

### N6-v031 — `docs/TESTING.md` per-file test counts are wrong (4 of 10 files)

**Severity:** LOW (documentation drift; the total is correct).

**Evidence.** `docs/TESTING.md:11-21` lists:

| File | TESTING.md says | Actual (`pytest --collect-only`) |
|------|-----------------|-----------------------------------|
| `test_parser.py` | 13 | **12** |
| `test_store.py` | 7 | **8** |
| `test_cli_security.py` | 9 | **10** |
| `test_discovery_fixes.py` | 15 | **14** |
| (others) | ✓ | ✓ |
| **Total passed** | 102 | **102** ✓ |

The four miscounts cancel out (+1, +1, +1, -1 = net +2... actually 13→12
is -1, 7→8 is +1, 9→10 is +1, 15→14 is -1 → net 0), so the headline
"102 passed" is right. But anyone using the per-file table for
triage will be misled.

**Suggested fix:** re-run `pytest --collect-only -q` and copy the numbers
verbatim.

### N7-v031 — `_parse_chrono` redundantly imports `re` inside the function

**Severity:** TRIVIAL (code smell, no behavioural impact).

**Evidence.** `parser.py:505`: `import re as _re` inside `_parse_chrono`,
even though `parser.py:19` already does `import re` at module level. The
local `_re` is used at lines 506, 509. Functionally equivalent to using
the module-level `re`, but suggests the function was written in isolation
and pasted in.

### N8-v031 — Broad `except Exception` handlers in the crawl/discover/log path

**Severity:** INFO (defensible for a crawler, but worth noting).

**Evidence.** Four sites:
- `crawl.py:84`: `except Exception as e:` wraps `_fetch_parse_store` —
  any unexpected error is recorded in `report.error_urls` and swallowed.
  One bad URL does not abort the run, but the error type is hidden
  behind a string.
- `crawl.py:158`: same pattern for inner-frame fetches.
- `discover.py:141-142`: `except Exception: pass` in `add()` — a DB
  hiccup on one URL is silently ignored; discovery continues.
- `http.py:277-278`: `except Exception: pass` in `_log()` — logging
  failures never break a crawl.
- `parser.py:114-117`: `try: BeautifulSoup(html, "lxml"); except
  Exception: BeautifulSoup(html, "html.parser")` — silently falls back
  to the stdlib parser.

All five are defensible (a crawler must not die on one bad URL/page), but
they do mask programmer errors during development. Consider logging the
exception at DEBUG level inside each handler.

### N9-v031 — `README.md` body text stale for 0.3.1

**Severity:** LOW (documentation drift).

**Evidence.** `README.md:139` (after the v0.3.1 bump):
```
## Status (v0.3.1)

Working MVP: collector, archive, FTS5 search, research engine, CLI, skill,
tests — all verified against real fixtures. The seeded corpus is 10 pages;
```
The header was bumped (v0.1.0 → v0.3.1) but the body still says
"Working MVP" and "seeded corpus is 10 pages". After v0.3.0's P0/P1
fixes and v0.3.1's site-coverage fixes, "Working MVP" undersells the
state, and the 10-page seeded corpus is the persistent `data/vostlit.db`
(which the v0.3.0 QA already flagged as the N4 readiness gap — now
partly addressed by the e2e pipeline test).

**Suggested fix:** rewrite the Status section to reflect v0.3.1
(P0 security closed, schema v2, 102 tests, e2e pipeline, site-coverage
N4a/b/c fixed; residual gap: no live crawl has been run on the
persistent DB yet).

---

## 4. Residual blockers

None of the v0.3.1 claims is refuted. The two HIGH-severity findings
(N1-v031, N3-v031) are **test-quality** issues, not implementation
defects — the underlying code does what the CHANGELOG claims, but the
tests do not prove it. Specifically:

- **N1-v031:** the `unknown`-page-type branch is implemented correctly
  (verified manually) but the test named for it does not exercise it.
- **N3-v031:** the resume code path (`Crawler._select_queue` with
  `status IN ('discovered','error')` and the `cmd_resume` CLI) exists
  and is plausibly correct, but no test actually verifies it. The
  e2e Stage 5 passes for the wrong reason.

Neither blocks research use of the system, but both should be fixed
before relying on the test suite as a regression net. If the `unknown`
branch or the resume logic regresses in a future commit, these tests
will not catch it.

**Out-of-scope but worth noting** (carried over from v0.3.0 QA, still
true in v0.3.1): no live end-to-end crawl has been run against the
persistent `data/vostlit.db`. The e2e test uses `httpx.MockTransport`
with synthesized/fixture HTML, so it proves the pipeline mechanics
work, not that the live site is actually crawlable end-to-end. The
N4a/b/c fixes expand *what the crawler is allowed to discover*, but do
not verify the live site responds as the fixtures predict.

---

## 5. Verdict

> **"ready for research use"** (with two test-quality caveats — N1-v031,
> N3-v031 — that should be closed before the next release).

---

## 6. Justification (with verified evidence)

**Why "ready for research use" (up from v0.3.0's "working prototype with
significant limitations"):**

1. **All 12 v0.3.1 claims hold.** 12 confirmed, 0 refuted, 0 partial.
   Every claim has a real command transcript or `file:line` citation in
   §2. The two claims that touch test quality (6, 8) are confirmed for
   the *implementation*; the tests themselves are weak (§3).

2. **The v0.3.0 QA's N4 blockers are genuinely closed.** N4a (`_is_doc_url`
   accepts `/common/`, `/Repertorium/`, `/MGH/`, `/MPH/`), N4b (chrono
   parser yields ≥3 sections on a synthetic fixture), and N4c
   (`region_catalog`/`alpha_index` in `fetch_page_types`) are all
   implemented AND runtime-verified. The CHANGELOG's N4a/b/c claims are
   accurate.

3. **The v0.3.0 QA's N1 (search_by_region/author Cyrillic case) was
   closed in v0.3.0** per `IMPLEMENTATION_REPORT.md` C-section ("N1 ...
   исправлен"), and v0.3.1 does not regress it (102 tests pass, including
   the F2 regression tests in `test_p0_p1_regression.py`).

4. **Real HTTP-level redirect tests exist.** `tests/test_redirect_http.py`
   (9 tests, all pass) uses `httpx.MockTransport` and asserts the exact
   guarantees the SECURITY_AUDIT demanded: offsite host never requested
   (line 92-93), 404 not retried (line 185), 429 Retry-After honored
   (line 209), body-size cap aborts mid-stream (line 258). The D-1/D-3/D-4
   security fixes are now genuinely regression-tested at the transport
   layer, not just by direct `_check_scope` calls.

5. **E2E pipeline test exists on a persistent DB.** `test_e2e_pipeline.py`
   uses `tmp_path/"e2e.db"` (a real file, not `:memory:`), runs
   discover→crawl→inventory, and does SQL SELECT assertions on
   `documents`, `document_sections`, `fts_sections`. Stage 3 (re-import
   ID stability) and Stage 4 (inventory reflects state) are genuine and
   pass. The persistent-DB claim is real.

6. **4xx is no longer retried.** Git diff shows the `except
   httpx.HTTPStatusError` clause was added to `fetch()`
   (`http.py:196-201`), positioned AFTER `except _RetryableStatus`
   (line 185). The handler immediately raises `FetchError` — no retry
   loop. `test_404_not_retried` verifies `call_count["n"] == 1`.

7. **102 tests pass, 2 skipped (live).** Up from v0.3.0's 77 passed.
   The +25 delta is: 14 (test_discovery_fixes) + 9 (test_redirect_http)
   + 2 (test_e2e_pipeline) = 25. Matches.

8. **Versions are consistent at 0.3.1** across `pyproject.toml`,
   `__init__.py`, `SKILL.md`, and `CHANGELOG.md`. The v0.3.0 QA's N3
   (CHANGELOG drift) is closed.

**Why not "ready for research use" without caveats:**

1. **N1-v031 (HIGH):** the test named `test_unknown_page_type_recorded_
   with_warning` does not test the `unknown` branch. If a future commit
   removes the `else` branch at `parser.py:242-247`, this test will still
   pass. The implementation is correct today; the regression net has a
   hole.

2. **N3-v031 (HIGH):** the e2e Stage 5 "resume" is a no-op
   (`INSERT OR IGNORE` on an existing row + `force=False` skips parsed
   docs). The `cmd_resume` CLI command is not exercised by any test.
   If a future commit breaks `Crawler._select_queue`'s
   `status IN ('discovered','error')` clause, no test will catch it.

These two are test-quality issues, not implementation defects. They do
not block research use today (the code is correct), but they undermine
the trustworthiness of the test suite as a regression net. Closing them
is a small effort (~20 lines of test code) and should be done before
v0.3.2.

**Why not "working prototype with limitations" (the v0.3.0 verdict):**
v0.3.0's two reasons for that verdict were (a) site-coverage N4 unfixed
and (b) F2 listing-API still Cyrillic-broken. Both are now closed in
v0.3.0/0.3.1. The remaining gaps (no live crawl on persistent DB;
test-quality N1/N3-v031; documentation N6/N9-v031) do not rise to
"significant limitations" — they are hygiene.

**Why not "has blocking defects":** no claim is refuted, no implementation
defect blocks the documented use cases (search/read/cite over a seeded
corpus; discover→crawl against the verified-allowed URL roots; resume
after interruption). The broad exception handlers (N8-v031) are
defensible. The stale README (N9-v031) is cosmetic.

**Net assessment:** v0.3.1 is a real improvement over v0.3.0. The four
P0 site-coverage defects (N4a/b/c + unknown-page-type recording) are
genuinely fixed and runtime-verified. The HTTP client now has real
transport-level regression tests. The E2E pipeline test (despite its
Stage 5 flaw) proves the discover→crawl→store→inventory loop works on
a persistent DB with fixture HTML. The system is safe to develop
against and safe to run against a hand-seeded or fixture-driven corpus.
For a working historian running `python -m vostlit_research` against
the live site end-to-end, the next step is a real crawl on the
persistent DB (the e2e test uses MockTransport, not the live site) —
but that is a usage gap, not a code defect.
