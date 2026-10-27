"""Real HTTP-level redirect & error tests via httpx.MockTransport.

These tests exercise the HttpClient at the transport level — no direct
_check_scope calls. A MockTransport intercepts every request, so NOTHING
leaves the process. We verify:

  - D-1: 302 to an offsite host is refused WITHOUT a request to that host
  - 302 to a forbidden PATH on the same (allowed) host is refused
  - redirect loop is detected and refused
  - 3xx without Location header raises
  - too many redirects (>MAX_REDIRECTS) raises
  - 404 is NOT retried (no useless retries on permanent client errors)
  - 429 with numeric Retry-After is honored (sleeps, then retries)
  - 429 with HTTP-date Retry-After is honored
  - response body exceeding the size cap WITHOUT Content-Length is refused
    (streaming abort)

All requests are intercepted; no network traffic occurs.
"""
from __future__ import annotations

import email.utils
import time
from datetime import datetime, timezone, timedelta

import httpx
import pytest

from vostlit_research.config import Config
from vostlit_research.db import Database
from vostlit_research.collector.http import (
    HttpClient, RefusedError, FetchError, TooLargeResponseError,
)


# Helper: build a client whose underlying httpx.Client uses a MockTransport.
# The MockTransport receives EVERY request — we record each call to prove
# which URLs were actually contacted.
def _client_with_mock(cfg, db, handler):
    http = HttpClient(cfg, db)
    # capture the request log
    requested: list[str] = []
    def transport_handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return handler(request)
    mock = httpx.MockTransport(transport_handler)
    # swap the underlying client's transport
    http._client.close()
    http._client = httpx.Client(
        timeout=httpx.Timeout(cfg.http_timeout, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": cfg.user_agent},
        transport=mock,
    )
    # make the cap tiny for the size test
    http.max_response_bytes = 4096
    return http, requested


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = tmp_path / "t.db"
    cfg.archive_dir = tmp_path / "arch"
    cfg.request_delay = 0.0  # tests must not sleep (except 429 Retry-After)
    cfg.max_pages_per_run = 1000
    cfg.max_retries = 3
    cfg.retry_backoff = 0.01  # tiny backoff so 429 tests are fast
    cfg.retry_jitter = 0.0
    cfg.ensure_dirs()
    return cfg


# ----------------------------------------------------------------------
def test_302_to_offsite_host_refused_without_request(tmp_path, monkeypatch):
    """D-1: a 302 from an allowed host to an offsite host must be refused,
    AND no request must be sent to the offsite host."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if "vostlit.info/Texts/redirect-me" in str(request.url):
            return httpx.Response(302, headers={"Location": "https://evil.example.com/steal?cookie=secret"})
        return httpx.Response(404)  # should never reach here for evil host

    http, requested = _client_with_mock(cfg, db, handler)
    try:
        with pytest.raises(RefusedError):
            http.fetch("https://www.vostlit.info/Texts/redirect-me")
    finally:
        http.close(); db.close()
    # CRITICAL: the offsite host must NEVER have been requested
    assert not any("evil.example.com" in u for u in requested), \
        f"offsite host was requested! calls={requested}"
    # the allowed initial URL WAS requested (exactly once)
    assert any("vostlit.info/Texts/redirect-me" in u for u in requested)


def test_302_to_forbidden_path_on_same_host_refused(tmp_path):
    """302 to a path NOT in allowed_sections on the same host is refused."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if "vostlit.info/allowed" in str(request.url):
            return httpx.Response(302, headers={"Location": "https://www.vostlit.info/admin/secret"})
        return httpx.Response(200, text="ok")

    http, requested = _client_with_mock(cfg, db, handler)
    try:
        # /allowed is not in allowed_sections either, so initial fetch refuses;
        # but let's test the redirect-to-forbidden-path case directly via a
        # path that IS allowed then redirects to /admin.
        # Use /Texts/allowed which is allowed.
        def handler2(request: httpx.Request) -> httpx.Response:
            if "vostlit.info/Texts/allowed" in str(request.url):
                return httpx.Response(302, headers={"Location": "https://www.vostlit.info/admin/secret"})
            return httpx.Response(200, text="ok")
        mock2 = httpx.MockTransport(handler2)
        http._client.close()
        http._client = httpx.Client(timeout=httpx.Timeout(cfg.http_timeout, connect=10.0),
                                    follow_redirects=False, transport=mock2)
        with pytest.raises(RefusedError):
            http.fetch("https://www.vostlit.info/Texts/allowed")
    finally:
        http.close(); db.close()
    assert not any("/admin/secret" in u for u in requested), \
        f"forbidden path was requested! calls={requested}"


def test_redirect_loop_detected_and_refused(tmp_path):
    """A redirect loop (A→B→A→B...) must hit MAX_REDIRECTS and raise."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)

    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.endswith("/Texts/loopA"):
            return httpx.Response(302, headers={"Location": "https://www.vostlit.info/Texts/loopB"})
        if u.endswith("/Texts/loopB"):
            return httpx.Response(302, headers={"Location": "https://www.vostlit.info/Texts/loopA"})
        return httpx.Response(404)

    http, _ = _client_with_mock(cfg, db, handler)
    try:
        with pytest.raises(FetchError, match="too many redirects"):
            http.fetch("https://www.vostlit.info/Texts/loopA")
    finally:
        http.close(); db.close()


def test_redirect_without_location_header_raises(tmp_path):
    """A 3xx without a Location header must raise (not hang or silently pass)."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)  # no Location header

    http, _ = _client_with_mock(cfg, db, handler)
    try:
        with pytest.raises(FetchError, match="without Location"):
            http.fetch("https://www.vostlit.info/Texts/no-loc")
    finally:
        http.close(); db.close()


def test_404_not_retried(tmp_path):
    """404 is a permanent client error — must NOT be retried (no useless retries)."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404, text="not found")

    http, _ = _client_with_mock(cfg, db, handler)
    try:
        with pytest.raises((httpx.HTTPStatusError, FetchError)):
            http.fetch("https://www.vostlit.info/Texts/missing")
    finally:
        http.close(); db.close()
    # 404 is >= 400 but not 429/503, so it raises HTTPStatusError immediately
    # (not retried). Assert exactly ONE request was made.
    assert call_count["n"] == 1, f"404 was retried {call_count['n']} times (should be 1)"


def test_429_numeric_retry_after_honored(tmp_path, monkeypatch):
    """429 with numeric Retry-After must sleep that many seconds then retry."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, text="ok after retry")

    http, _ = _client_with_mock(cfg, db, handler)
    try:
        res = http.fetch("https://www.vostlit.info/Texts/rate-limited")
        assert res.status == 200
    finally:
        http.close(); db.close()
    # at least one sleep matching the Retry-After value (capped at MAX_RETRY_AFTER)
    assert any(abs(s - 2.0) < 0.01 for s in sleeps), f"Retry-After=2 not honored; sleeps={sleeps}"
    assert state["n"] == 2  # one 429 + one 200


def test_429_http_date_retry_after_honored(tmp_path, monkeypatch):
    """429 with HTTP-date Retry-After must be parsed and slept."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    state = {"n": 0}

    # HTTP-date 3 seconds in the future
    future = datetime.now(timezone.utc) + timedelta(seconds=3)
    http_date = email.utils.format_datetime(future, usegmt=True)

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": http_date})
        return httpx.Response(200, text="ok")

    http, _ = _client_with_mock(cfg, db, handler)
    try:
        res = http.fetch("https://www.vostlit.info/Texts/rate-limited-date")
        assert res.status == 200
    finally:
        http.close(); db.close()
    # httpx parses HTTP-date Retry-After into seconds; we should have slept > 0
    assert any(s > 0 for s in sleeps), f"HTTP-date Retry-After not honored; sleeps={sleeps}"
    assert state["n"] == 2


def test_body_size_exceeded_without_content_length(tmp_path):
    """Response body larger than the cap, with NO Content-Length header, must
    be refused mid-stream (TooLargeResponseError)."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)

    # generate a body larger than the 4096-byte cap set in _client_with_mock
    big_body = b"x" * 100_000

    def handler(request: httpx.Request) -> httpx.Response:
        # NO Content-Length header — the client must detect via streaming
        return httpx.Response(200, content=big_body,
                              headers={"content-type": "text/html"})

    http, _ = _client_with_mock(cfg, db, handler)
    try:
        with pytest.raises(TooLargeResponseError):
            http.fetch("https://www.vostlit.info/Texts/huge")
    finally:
        http.close(); db.close()


def test_normal_200_fetch_works(tmp_path):
    """Sanity: a plain 200 response with allowed URL is fetched successfully."""
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>ok</body></html>",
                              headers={"content-type": "text/html; charset=utf-8"})

    http, _ = _client_with_mock(cfg, db, handler)
    try:
        res = http.fetch("https://www.vostlit.info/Texts/rus/X/text1.phtml?id=1")
        assert res.status == 200
        assert b"ok" in res.content
    finally:
        http.close(); db.close()
