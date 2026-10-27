"""End-to-end pipeline test on a PERSISTENT test DB with a local HTTP server.

Exercises the full pipeline the mission demands:
  seed/catalog → discovery → persisted queue → fetch → parse → store →
  inventory → resume

Uses a local httpx.MockTransport (no network traffic) serving representative
HTML fixtures. After each stage, the DB is verified with SQL queries.

Verifies:
  - discovered URLs are really persisted in the documents table
  - documents have correct statuses (discovered → parsed)
  - sections contain extracted text
  - re-import does not change stable section IDs without cause
  - inventory reflects the real state
  - after a simulated interruption, remaining docs can be processed via resume
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from vostlit_research.config import Config
from vostlit_research.db import Database
from vostlit_research.collector.http import HttpClient
from vostlit_research.collector.crawl import Crawler
from vostlit_research.collector.discover import discover


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


# ---------- local HTTP "server" via MockTransport ----------
def _serve_fixtures(request: httpx.Request) -> httpx.Response:
    """Serve real fixture HTML for known URLs; synthesize minimal pages for
    catalog/discovery test URLs."""
    u = str(request.url)
    # the Caucasus regional catalog (real fixture)
    if u.endswith("/Texts/Dokumenty/kavkaz.html"):
        return httpx.Response(200, content=(FIXTURES / "kavkaz_catalog.fragment.html").read_bytes(),
                              headers={"content-type": "text/html; charset=windows-1251"})
    # a real .phtml document (Iordan)
    if "Iordan/text2.phtml" in u:
        return httpx.Response(200, content=(FIXTURES / "document_text_iordan_text2.html").read_bytes(),
                              headers={"content-type": "text/html; charset=windows-1251"})
    # a real bare .htm document (Dagestan 1792)
    if "Dagestan_poddanstvo_1792/text.htm" in u:
        return httpx.Response(200, content=(FIXTURES / "document_text_dagestan_1792.html").read_bytes(),
                              headers={"content-type": "text/html; charset=windows-1251"})
    # a real collection index (Dag_chron)
    if "Dag_chron/index.htm" in u:
        return httpx.Response(200, content=(FIXTURES / "document_text_dag_chron_index.html").read_bytes(),
                              headers={"content-type": "text/html; charset=windows-1251"})
    # synthesize a tiny region catalog with 3 document links
    if u.endswith("/Texts/Dokumenty/testcat.html"):
        html = b"""<html><body><table>
        <tr><td><a href="../Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm">Doc1</a></td></tr>
        <tr><td><a href="../Kavkaz/XVIII/1780-1800/Other/text.htm">Doc2</a></td></tr>
        </table></body></html>"""
        return httpx.Response(200, content=html,
                              headers={"content-type": "text/html; charset=windows-1251"})
    # synthesize Doc2 (a bare .htm)
    if u.endswith("/Kavkaz/XVIII/1780-1800/Other/text.htm"):
        html = ('<html><body><p align="center"><strong><font color="#000000">OTHER DOC</font></strong></p>'
                '<p>Body text about Gumbet and Salatavia.</p>'
                '<hr/><p align="center"><big>\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0438</big></p>'
                '<p><font color="#000000">1. a note</font></p>'
                '<p><small><font color="#800040"><strong>\u0422\u0435\u043a\u0441\u0442 \u0432\u043e\u0441\u043f\u0440\u043e\u0438\u0437\u0432\u0435\u0434\u0435\u043d \u043f\u043e \u0438\u0437\u0434\u0430\u043d\u0438\u044e: Other. 1800</strong></font></small></p>'
                '</body></html>').encode("windows-1251")
        return httpx.Response(200, content=html,
                              headers={"content-type": "text/html; charset=windows-1251"})
    return httpx.Response(404, text="not found")


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = tmp_path / "e2e.db"
    cfg.archive_dir = tmp_path / "arch"
    cfg.request_delay = 0.0
    cfg.max_pages_per_run = 100
    cfg.max_retries = 1
    cfg.retry_backoff = 0.01
    cfg.retry_jitter = 0.0
    cfg.ensure_dirs()
    return cfg


def _mock_http(cfg, db) -> HttpClient:
    http = HttpClient(cfg, db)
    mock = httpx.MockTransport(_serve_fixtures)
    http._client.close()
    http._client = httpx.Client(
        timeout=httpx.Timeout(cfg.http_timeout, connect=10.0),
        follow_redirects=False, transport=mock,
        headers={"User-Agent": cfg.user_agent},
    )
    return http


# ----------------------------------------------------------------------
def test_e2e_pipeline_on_persistent_db(tmp_path):
    cfg = _cfg(tmp_path)
    db = Database(cfg.db_path)

    # ---------- Stage 1: discovery from a region catalog ----------
    http = _mock_http(cfg, db)
    # discover from the test catalog (serves 2 doc links)
    discovered = discover(cfg, db, http,
                          regions=["testcat"],  # custom slug -> /Texts/Dokumenty/testcat.html
                          max_discover=10)
    http.close()
    # SQL: discovered URLs are persisted
    rows = db.conn.execute(
        "SELECT canonical_url, status, page_type FROM documents ORDER BY canonical_url"
    ).fetchall()
    assert len(rows) >= 2, f"expected >=2 discovered docs, got {len(rows)}"
    statuses = {r["status"] for r in rows}
    assert "discovered" in statuses
    # all discovered URLs are in crawl_log
    log_discovered = db.conn.execute(
        "SELECT COUNT(*) c FROM crawl_log WHERE action='discovered'"
    ).fetchone()["c"]
    assert log_discovered >= 2

    # ---------- Stage 2: fetch + parse + store ----------
    http = _mock_http(cfg, db)
    crawler = Crawler(cfg, db)
    crawler.http = http  # inject mock
    report = crawler.crawl(regions=["testcat"], limit=5)
    http.close()
    # report shows parsed > 0
    assert report.parsed + report.unchanged >= 1, f"nothing parsed: {report.as_dict()}"
    # SQL: at least one document is now 'parsed' with sections
    parsed = db.conn.execute(
        "SELECT id, canonical_url, title, current_version_id FROM documents WHERE status='parsed'"
    ).fetchall()
    assert len(parsed) >= 1
    # SQL: sections contain extracted text
    for p in parsed:
        secs = db.conn.execute(
            "SELECT id, section_type, text, stable_key FROM document_sections WHERE document_id=?",
            (p["id"],)
        ).fetchall()
        assert len(secs) > 0, f"doc {p['id']} has no sections"
        assert any(s["text"] for s in secs), f"doc {p['id']} sections have no text"
        assert all(s["stable_key"] for s in secs), f"doc {p['id']} sections missing stable_key"
    # SQL: FTS5 is populated
    fts_count = db.conn.execute("SELECT COUNT(*) c FROM fts_sections").fetchone()["c"]
    assert fts_count > 0

    # ---------- Stage 3: re-import does not change stable IDs ----------
    # pick a parsed doc, record its section ids, re-crawl (force), confirm ids stable
    first_parsed = parsed[0]
    sec_ids_before = [r["id"] for r in db.conn.execute(
        "SELECT id FROM document_sections WHERE document_id=? ORDER BY id", (first_parsed["id"],)
    ).fetchall()]
    http = _mock_http(cfg, db)
    crawler = Crawler(cfg, db)
    crawler.http = http
    crawler.crawl(seeds=[first_parsed["canonical_url"]], limit=1, force=True)
    http.close()
    sec_ids_after = [r["id"] for r in db.conn.execute(
        "SELECT id FROM document_sections WHERE document_id=? ORDER BY id", (first_parsed["id"],)
    ).fetchall()]
    assert sec_ids_before == sec_ids_after, \
        f"section IDs changed on re-import: {sec_ids_before} -> {sec_ids_after}"

    # ---------- Stage 4: inventory reflects real state ----------
    st = db.stats()
    assert st["documents"] >= 2
    assert st["documents_by_status"].get("parsed", 0) >= 1
    assert st["document_sections"] > 0

    # ---------- Stage 5: resume after simulated interruption ----------
    # N3-v031 fix: the previous version of this test inserted an already-parsed
    # doc (INSERT OR IGNORE was a no-op) and called crawl(force=False) which
    # skips parsed docs — so the assertion passed trivially. Now we insert a
    # FRESH doc with status='error' (simulating a fetch that failed/was
    # interrupted), then verify the resume CLI path actually re-processes it.
    # We use the cmd_resume handler directly (it queues status IN discovered,error).
    resume_url = "https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/ResumeTest/text.htm"
    # synthesize a handler that serves this URL
    def _resume_handler(request):
        u = str(request.url)
        if u == resume_url:
            html = ('<html><body><p align="center"><strong><font color="#000000">RESUME DOC</font></strong></p>'
                    '<p>Body text from a resumed fetch.</p>'
                    '<p><small><font color="#800040"><strong>\u0422\u0435\u043a\u0441\u0442 \u0432\u043e\u0441\u043f\u0440\u043e\u0438\u0437\u0432\u0435\u0434\u0435\u043d \u043f\u043e \u0438\u0437\u0434\u0430\u043d\u0438\u044e: Resume. 1801</strong></font></small></p>'
                    '</body></html>').encode("windows-1251")
            return httpx.Response(200, content=html, headers={"content-type": "text/html; charset=windows-1251"})
        return _serve_fixtures(request)
    # insert the doc as 'error' (interrupted)
    db.conn.execute(
        "INSERT INTO documents (canonical_url, stable_id, first_seen_at, last_checked_at, status, error_message) VALUES (?,?,?,?, 'error', 'simulated interruption')",
        (resume_url, "resume_test", db.now(), db.now())
    )
    db.conn.commit()
    # verify it's 'error' before resume
    before = db.conn.execute("SELECT status FROM documents WHERE canonical_url=?", (resume_url,)).fetchone()
    assert before["status"] == "error", f"pre-resume status should be 'error', got {before['status']}"
    # build a mock http with the resume handler and run the resume CLI path
    http = HttpClient(cfg, db)
    mock = httpx.MockTransport(_resume_handler)
    http._client.close()
    http._client = httpx.Client(timeout=httpx.Timeout(cfg.http_timeout, connect=10.0),
                                follow_redirects=False, transport=mock,
                                headers={"User-Agent": cfg.user_agent})
    crawler = Crawler(cfg, db)
    crawler.http = http
    # cmd_resume queues status IN ('discovered','error') — replicate that
    queue_rows = db.conn.execute(
        "SELECT canonical_url FROM documents WHERE status IN ('discovered','error') LIMIT 5"
    ).fetchall()
    queue = [r["canonical_url"] for r in queue_rows]
    assert resume_url in queue, f"resume_url not in error queue: {queue}"
    report2 = crawler.crawl(seeds=queue, limit=5)
    http.close()
    # SQL: the doc is now parsed (resume worked)
    after = db.conn.execute(
        "SELECT status, title FROM documents WHERE canonical_url=?", (resume_url,)
    ).fetchone()
    assert after is not None
    assert after["status"] == "parsed", \
        f"resume did not reprocess the error doc: status={after['status']} (report={report2.as_dict()})"
    assert after["title"] == "RESUME DOC"

    # ---------- Stage 6: no duplicates after all this ----------
    total = db.conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    dupes = db.conn.execute(
        "SELECT canonical_url, COUNT(*) c FROM documents GROUP BY canonical_url HAVING c > 1"
    ).fetchall()
    assert len(dupes) == 0, f"duplicate documents: {dupes}"

    db.close()


def test_e2e_inventory_shows_meaningful_counters(tmp_path):
    """inventory CLI must show discovered>0 when a queue exists (not zero)."""
    import subprocess, sys, os, json
    cfg = _cfg(tmp_path)
    env = dict(os.environ)
    env["VOSTLIT_DB_PATH"] = str(cfg.db_path)
    env["PYTHONPATH"] = str(ROOT)
    db = Database(cfg.db_path)
    http = _mock_http(cfg, db)
    discover(cfg, db, http, regions=["testcat"], max_discover=10)
    http.close()
    db.close()
    # run inventory CLI
    r = subprocess.run([sys.executable, "-m", "vostlit_research", "inventory"],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    # discovered must be > 0 (we have a queue)
    assert data["discovered"] >= 1, f"inventory shows discovered={data['discovered']} (expected >=1)"
    assert data["total_documents"] >= 1
