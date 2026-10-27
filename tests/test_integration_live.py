"""Integration tests that touch the REAL vostlit.info site.

These are SKIP by default to avoid hammering the site. Run explicitly:

    VR_INTEGRATION=1 python -m pytest tests/test_integration_live.py -s

They fetch at most 2-3 pages with the polite client. If the site is
unreachable, they skip (not fail).
"""
from __future__ import annotations

import os
import socket

import pytest

from vostlit_research.config import Config
from vostlit_research.db import Database
from vostlit_research.collector.http import HttpClient
from vostlit_research.collector.parser import parse_page

RUN = os.environ.get("VR_INTEGRATION") == "1"


def _site_reachable() -> bool:
    try:
        with socket.create_connection(("www.vostlit.info", 443), timeout=8):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not RUN, reason="set VR_INTEGRATION=1 to run live site tests")
@pytest.mark.skipif(not _site_reachable(), reason="vostlit.info unreachable")
def test_live_homepage_parses(tmp_path):
    cfg = Config()
    cfg.db_path = tmp_path / "live.db"
    cfg.archive_dir = tmp_path / "archive"
    cfg.request_delay = 3.0
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        res = http.fetch(cfg.base_url)
        assert res.status == 200
        p = parse_page(cfg.base_url, res.content, charset="windows-1251")
        assert p.page_type == "home"
        assert "Восточная" in (p.title or "")
        assert p.links  # featured docs
    finally:
        http.close()
        db.close()


@pytest.mark.skipif(not RUN, reason="set VR_INTEGRATION=1 to run live site tests")
@pytest.mark.skipif(not _site_reachable(), reason="vostlit.info unreachable")
def test_live_one_document_parses(tmp_path):
    cfg = Config()
    cfg.db_path = tmp_path / "live.db"
    cfg.archive_dir = tmp_path / "archive"
    cfg.request_delay = 3.0
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        # a small bare .htm Dagestan document (verified in SITE_AUDIT.md)
        res = http.fetch("https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm")
        assert res.status == 200
        p = parse_page(res.url, res.content, charset="windows-1251")
        assert p.page_type == "document_text"
        assert p.title and "ПОДДАННЫХ" in p.title
        assert p.original_creation_date == "1792"
    finally:
        http.close()
        db.close()
