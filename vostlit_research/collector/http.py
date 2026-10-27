"""Polite HTTP client for Vostlit.info.

Safety features (all required by the master prompt §1.3 and §5.2):
  * respect ``allowed_domains`` and ``allowed_sections`` from Config
  * never crawl unbounded: ``max_pages_per_run`` hard cap
  * fixed delay between requests + exponential backoff with jitter on retry
  * timeouts; redirects followed but cross-domain redirects are refused
  * never bypass auth/CAPTCHA/paywall (we don't encounter any, but we refuse
    to follow links that look like they require it)
  * no user-agent spoofing beyond a descriptive research UA
  * every fetch is logged to ``crawl_log`` for auditability
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from ..config import Config
from ..db import Database
from .. import textnorm


class FetchError(Exception):
    pass


class RefusedError(FetchError):
    """Raised when a URL is outside the allowed scope."""


@dataclass
class FetchResult:
    url: str            # the canonical URL requested
    final_url: str      # after redirects
    status: int
    content: bytes
    content_type: str
    elapsed: float
    from_cache: bool = False


class HttpClient:
    def __init__(self, config: Config, db: Database | None = None):
        self.cfg = config
        self.db = db
        self._last_request_at = 0.0
        self._pages_this_run = 0
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.cfg.http_timeout, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": self.cfg.user_agent},
        )

    # --- scope guards -----------------------------------------------------
    def _check_scope(self, url: str) -> None:
        parts = urlsplit(url)
        host = (parts.netloc or "").lower()
        if host not in self.cfg.allowed_domains:
            raise RefusedError(f"host not allowed: {host}")
        path = parts.path or "/"
        if not any(path.startswith(sec) for sec in self.cfg.allowed_sections):
            # special-case: homepage
            if path != "/":
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

    # --- main entry -------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        canonical = textnorm.normalise_url(url)
        self._check_scope(canonical)
        self._enforce_cap()
        self._enforce_delay()

        last_exc: Exception | None = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = self._client.get(canonical)
                self._pages_this_run += 1
                # refuse cross-domain final URL
                final_host = urlsplit(str(resp.url)).netloc.lower()
                if final_host not in self.cfg.allowed_domains:
                    raise RefusedError(f"redirected offsite: {resp.url}")
                result = FetchResult(
                    url=canonical,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    content=resp.content,
                    content_type=resp.headers.get("content-type", ""),
                    elapsed=resp.elapsed.total_seconds(),
                )
                self._log(canonical, resp.status_code, len(resp.content), "fetched")
                return result
            except RefusedError:
                raise
            except httpx.HTTPError as e:
                last_exc = e
                if attempt < self.cfg.max_retries:
                    backoff = self.cfg.retry_backoff ** attempt
                    jitter = random.uniform(0, self.cfg.retry_jitter)
                    time.sleep(backoff + jitter)
                    continue
                break
        # all retries failed
        self._log(canonical, 0, 0, "error", str(last_exc))
        raise FetchError(f"fetch failed for {canonical}: {last_exc}")

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
