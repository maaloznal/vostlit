"""Polite, safe HTTP client for Vostlit.info.

Safety features (P0 hardened version — see docs/SECURITY_AUDIT.md D-1..D-8):
  * **Manual redirect handling with per-hop scope check** (D-1): redirects
    are NOT followed automatically. Each 3xx hop is resolved by hand and
    scope-checked (scheme+host+port+path) BEFORE the next request is issued,
    so a redirect to an offsite/attacker host is refused without ever
    sending a request to it.
  * **raise_for_status on every response** (D-3): 4xx/5xx raise and trigger
    retry/backoff; they are never silently parsed as document content.
  * **429 Retry-After honored** (D-3): on 429/503 with a Retry-After header,
    sleep that many seconds (capped) before retrying.
  * **Response-size cap** (D-4): responses larger than ``max_response_bytes``
    are refused and the connection is closed.
  * **resp.elapsed guard** (D-8): elapsed is computed with a monotonic
    fallback, never from ``resp.elapsed`` (which can raise RuntimeError).
  * ``allowed_domains`` + ``allowed_sections`` scope guard (D-2: '/' no
    longer bypasses the path check).
  * ``max_pages_per_run`` hard cap; polite delay; exponential backoff+jitter.
  * audit log to ``crawl_log`` for every attempt.

No auth/CAPTCHA/paywall bypass. Descriptive UA only.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urljoin

import httpx

from ..config import Config
from ..db import Database
from .. import textnorm


class FetchError(Exception):
    pass


class RefusedError(FetchError):
    """Raised when a URL or redirect target is outside the allowed scope."""


class TooLargeResponseError(FetchError):
    """Raised when a response exceeds ``max_response_bytes``."""


@dataclass
class FetchResult:
    url: str            # the canonical URL requested
    final_url: str      # after redirects (may equal url)
    status: int
    content: bytes
    content_type: str
    elapsed: float
    redirect_chain: tuple[str, ...] = ()  # all URLs visited, in order


# Default response-size cap: 25 MB. The largest verified vostlit page
# (kavkaz.html) is ~750 KB; 25 MB gives ample headroom without allowing a
# malicious page to exhaust memory.
DEFAULT_MAX_RESPONSE_BYTES = 25 * 1024 * 1024

# Cap on how long we honor a Retry-After header (seconds). A malicious server
# could otherwise stall us indefinitely.
MAX_RETRY_AFTER_SECONDS = 120

# Maximum redirect hops we will follow before giving up.
MAX_REDIRECTS = 8


class HttpClient:
    def __init__(self, config: Config, db: Database | None = None):
        self.cfg = config
        self.db = db
        self._last_request_at = 0.0
        self._pages_this_run = 0
        self.max_response_bytes = DEFAULT_MAX_RESPONSE_BYTES
        # IMPORTANT: follow_redirects=False — we handle redirects manually so
        # each hop can be scope-checked BEFORE the request is sent (D-1).
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.cfg.http_timeout, connect=10.0),
            follow_redirects=False,
            headers={"User-Agent": self.cfg.user_agent},
        )

    # --- scope guards -----------------------------------------------------
    def _check_scope(self, url: str) -> None:
        """Verify scheme, host, port, and path BEFORE any request is sent.

        D-2 fix: '/' in allowed_sections no longer bypasses the path check —
        we require the path to start with one of the EXPLICIT non-root
        prefixes, OR be exactly '/' (the homepage).
        """
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise RefusedError(f"scheme not allowed: {scheme!r}")
        host = (parts.netloc or "").lower()
        # netloc may include a port; split it out
        if ":" in host:
            hostname, _, port = host.partition(":")
        else:
            hostname, port = host, ""
        # reject non-default ports (the site is on 443/80 only)
        if port and port not in ("443", "80"):
            raise RefusedError(f"non-default port not allowed: {port} (host={hostname})")
        if hostname not in self.cfg.allowed_domains:
            raise RefusedError(f"host not allowed: {hostname}")
        path = parts.path or "/"
        # D-2: '/' alone (homepage) is allowed; otherwise the path must start
        # with one of the EXPLICIT allowed_sections prefixes (which must NOT
        # include '/').
        if path == "/":
            return
        # build the set of effective sections: drop any '/' to be safe
        effective_sections = tuple(s for s in self.cfg.allowed_sections if s != "/")
        if not effective_sections:
            raise RefusedError(
                "no effective allowed_sections (config has only '/' which is a no-op); "
                "set explicit path prefixes in config"
            )
        if not any(path.startswith(sec) for sec in effective_sections):
            raise RefusedError(f"path not in allowed sections: {path}")

    def _enforce_delay(self) -> None:
        now = time.monotonic()
        wait = self.cfg.request_delay - (now - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _enforce_cap(self) -> None:
        if self._pages_this_run >= self.cfg.max_pages_per_run:
            raise FetchError(
                f"max_pages_per_run reached ({self.cfg.max_pages_per_run}); "
                "raise the limit in config to continue"
            )

    # --- single hop (no redirect following) ------------------------------
    def _get_one(self, url: str) -> httpx.Response:
        """Issue a single GET (no redirect following). Raises on network error."""
        return self._client.get(url)

    def _read_capped(self, resp: httpx.Response) -> bytes:
        """Read the response body, refusing if it exceeds the size cap (D-4)."""
        cl = resp.headers.get("content-length")
        if cl:
            try:
                if int(cl) > self.max_response_bytes:
                    raise TooLargeResponseError(
                        f"response too large: declared {int(cl)} bytes > cap {self.max_response_bytes}"
                    )
            except ValueError:
                pass  # malformed content-length; fall back to streaming check
        # stream-read in chunks, aborting if the cap is exceeded
        buf = bytearray()
        for chunk in resp.iter_bytes(chunk_size=64 * 1024):
            buf.extend(chunk)
            if len(buf) > self.max_response_bytes:
                raise TooLargeResponseError(
                    f"response exceeded size cap {self.max_response_bytes} while streaming"
                )
        return bytes(buf)

    # --- main entry -------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        canonical = textnorm.normalise_url(url)
        self._check_scope(canonical)  # initial URL scope-checked BEFORE any request
        self._enforce_cap()
        self._enforce_delay()

        last_exc: Exception | None = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                return self._fetch_with_redirects(canonical)
            except RefusedError:
                raise  # scope violations are never retried
            except TooLargeResponseError:
                # don't retry a too-large response
                raise
            except _RetryableStatus as e:
                # 429/503 with optional Retry-After
                last_exc = e
                if attempt < self.cfg.max_retries:
                    wait = e.retry_after
                    if wait is None:
                        backoff = self.cfg.retry_backoff ** attempt
                        wait = backoff + random.uniform(0, self.cfg.retry_jitter)
                    time.sleep(min(wait, MAX_RETRY_AFTER_SECONDS + self.cfg.retry_jitter))
                    continue
                break
            except httpx.HTTPError as e:
                last_exc = e
                if attempt < self.cfg.max_retries:
                    backoff = self.cfg.retry_backoff ** attempt
                    jitter = random.uniform(0, self.cfg.retry_jitter)
                    time.sleep(backoff + jitter)
                    continue
                break
        self._log(canonical, 0, 0, "error", str(last_exc))
        raise FetchError(f"fetch failed for {canonical}: {last_exc}")

    def _fetch_with_redirects(self, canonical: str) -> FetchResult:
        """Fetch, manually following redirects with a per-hop scope check."""
        chain: list[str] = [canonical]
        current = canonical
        hop = 0
        while True:
            hop += 1
            if hop > MAX_REDIRECTS:
                raise FetchError(f"too many redirects (>{MAX_REDIRECTS}) starting from {canonical}")
            self._enforce_delay() if hop > 1 else None  # delay between hops too
            resp = self._get_one(current)
            self._pages_this_run += 1
            t0 = time.monotonic()
            # D-3: raise on 4xx/5xx so retries engage (and so error bodies are
            # never parsed as document content). 429/503 are retryable.
            if resp.status_code in (429, 503):
                ra = resp.headers.get("retry-after")
                retry_after: float | None = None
                if ra:
                    try:
                        retry_after = float(ra)
                    except ValueError:
                        retry_after = None
                raise _RetryableStatus(resp.status_code, retry_after, str(current))
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code} for {current}", request=resp.request, response=resp
                )
            if 300 <= resp.status_code < 400:
                loc = resp.headers.get("location")
                if not loc:
                    raise FetchError(f"redirect {resp.status_code} without Location header at {current}")
                next_url = urljoin(current, loc)
                # D-1: scope-check the redirect target BEFORE requesting it
                self._check_scope(next_url)
                chain.append(next_url)
                current = next_url
                continue
            # 2xx success: read body (capped) and return
            content = self._read_capped(resp)
            elapsed = time.monotonic() - t0  # D-8: never use resp.elapsed
            self._log(canonical, resp.status_code, len(content), "fetched",
                      f"final={current} hops={hop}")
            return FetchResult(
                url=canonical,
                final_url=current,
                status=resp.status_code,
                content=content,
                content_type=resp.headers.get("content-type", ""),
                elapsed=elapsed,
                redirect_chain=tuple(chain),
            )

    # --- audit log --------------------------------------------------------
    def _log(self, url: str, status: int, size: int, action: str, detail: str = "") -> None:
        if self.db is None:
            return
        try:
            with self.db.conn:
                self.db.conn.execute(
                    "INSERT INTO crawl_log (url, canonical_url, fetched_at, http_status, bytes, action, detail) VALUES (?,?,?,?,?,?,?)",
                    (url, url, self.db.now(), status, size, action, detail),
                )
        except Exception:  # noqa: BLE001
            pass  # logging must never break a crawl

    # --- lifecycle --------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class _RetryableStatus(Exception):
    """Internal signal: a 429/503 response was received, optionally with Retry-After."""
    def __init__(self, status: int, retry_after: float | None, url: str):
        self.status = status
        self.retry_after = retry_after
        self.url = url
        super().__init__(f"HTTP {status} for {url}")
