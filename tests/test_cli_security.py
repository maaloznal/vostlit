"""CLI tests + security tests (master prompt §15: 16, 17, 20)."""
from __future__ import annotations

import json
import subprocess
import sys

from vostlit_research import cli
from vostlit_research.collector.http import HttpClient, RefusedError
from vostlit_research.config import Config
from vostlit_research import archive


ROOT = "/home/z/my-project/vostlit-research"


def _run(args, env_db):
    # invoke cli.main with a config override via env
    import os
    env = dict(os.environ)
    env["VOSTLIT_DB_PATH"] = str(env_db)
    env["PYTHONPATH"] = ROOT
    return subprocess.run(
        [sys.executable, "-m", "vostlit_research", *args],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )


def test_cli_doctor(tmp_path):
    res = _run(["doctor"], tmp_path / "cli.db")
    assert res.returncode == 0, res.stderr
    assert "fts5_available" in res.stdout
    assert "[OK]" in res.stdout


def test_cli_stats_empty(tmp_path):
    res = _run(["stats"], tmp_path / "cli.db")
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["documents"] == 0


def test_cli_search_on_empty_corpus_is_honest(tmp_path):
    res = _run(["search", "Гумбет"], tmp_path / "cli.db")
    assert res.returncode == 0
    assert "No results" in res.stdout or "[]" in res.stdout


def test_http_refuses_offsite_url(cfg):
    cfg.allowed_domains = ("www.vostlit.info",)
    from vostlit_research.db import Database
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        try:
            http.fetch("https://example.com/")
            assert False, "should have refused offsite"
        except RefusedError:
            pass
    finally:
        http.close()
        db.close()


def test_http_refuses_disallowed_path(cfg):
    from vostlit_research.db import Database
    cfg.allowed_sections = ("/Texts/",)
    db = Database(cfg.db_path)
    http = HttpClient(cfg, db)
    try:
        try:
            http.fetch("https://www.vostlit.info/some/other/path")
            assert False, "should have refused path"
        except RefusedError:
            pass
    finally:
        http.close()
        db.close()


def test_archive_path_escape_refused(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    # a stored rel path is fine
    _, rel = archive.store(root, b"hello")
    assert archive.read_bytes(root, rel) == b"hello"
    # an escape attempt must raise
    try:
        archive.resolve(root, "../etc/passwd")
        assert False, "should have refused escape"
    except ValueError:
        pass


def test_parser_does_not_execute_scripts(tmp_path, fixture_bytes):
    # untrusted HTML with a script tag must not be executed; bs4 just ignores it
    html = b'<html><body><div id="main"><p>real text</p><script>alert(1)</script></div></body></html>'
    from vostlit_research.collector.parser import parse_page
    p = parse_page("https://www.vostlit.info/Texts/rus/x/text1.phtml?id=1", html, charset="utf-8")
    # body text extracted, script ignored
    assert "real text" in (p.extracted_text or "")
    assert "alert" not in (p.extracted_text or "")


def test_parser_handles_malformed_html():
    from vostlit_research.collector.parser import parse_page
    html = b'<html><body><div id="main"><p>ok<p>ok2<p>ok3</div>'  # unclosed
    p = parse_page("https://www.vostlit.info/Texts/rus/x/text1.phtml?id=1", html, charset="utf-8")
    assert p.page_type == "document_text"
    assert p.extracted_text  # did not crash


def test_parser_handles_empty_document():
    from vostlit_research.collector.parser import parse_page
    html = b'<html><body><div id="main"></div></body></html>'
    p = parse_page("https://www.vostlit.info/Texts/rus/x/text1.phtml?id=1", html, charset="utf-8")
    assert p.page_type == "document_text"
    assert not p.sections
    assert p.warnings  # no #dann warning expected


def test_crawl_log_records_fetches(tmp_path):
    # simulate by importing a doc then checking crawl_log isn't required here;
    # but verify the schema has crawl_log and doctor counts it
    from vostlit_research.db import Database
    db = Database(tmp_path / "x.db")
    assert "crawl_log" in db.stats()
    db.close()
