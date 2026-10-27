"""Crawl orchestrator: discover -> fetch -> parse -> store, with resume.

Design:
  * Discovery is separate from text-fetching (see discover.py).
  * The crawler is resumable: a document already in status ``parsed`` or
    ``unchanged`` is skipped unless ``force=True``.
  * The crawler never exceeds ``config.max_pages_per_run`` text fetches.
  * Region filter maps to a verified catalog (see REGIONS in discover.py).
  * Every fetch result is parsed by the verified parser (collector/parser.py)
    and stored via store.upsert_document, which handles de-dup and versioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..db import Database
from .. import store
from ..models import DocumentIn, SectionIn
from .http import HttpClient, FetchError, RefusedError
from .parser import parse_page, ParsedPage
from .discover import discover as _run_discover


@dataclass
class CrawlReport:
    discovered: int = 0
    fetched: int = 0
    parsed: int = 0
    unchanged: int = 0
    errors: int = 0
    skipped: int = 0
    error_urls: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        return d


class Crawler:
    def __init__(self, config: Config, db: Database):
        self.cfg = config
        self.db = db
        self.http = HttpClient(config, db)

    # --- public API -------------------------------------------------------
    def crawl(
        self,
        *,
        regions: list[str] | None = None,
        letters: list[str] | None = None,
        seeds: list[str] | None = None,
        include_home: bool = False,
        limit: int | None = None,
        force: bool = False,
        discover_only: bool = False,
    ) -> CrawlReport:
        report = CrawlReport()
        # 1. discover
        discovered = _run_discover(
            self.cfg, self.db, self.http,
            regions=regions, letters=letters, seeds=seeds,
            include_home=include_home,
            max_discover=limit * 3 if limit else None,
        )
        report.discovered = len(discovered)
        if discover_only:
            return report

        # 2. choose what to fetch (respect status, limit, page-type filter)
        queue = self._select_queue(discovered, force=force, limit=limit)
        # 3. fetch + parse + store
        for url in queue:
            try:
                self._fetch_parse_store(url, report)
            except RefusedError as e:
                report.errors += 1
                report.error_urls.append(f"{url} (refused: {e})")
            except FetchError as e:
                report.errors += 1
                report.error_urls.append(f"{url} ({e})")
            except Exception as e:  # noqa: BLE001
                report.errors += 1
                report.error_urls.append(f"{url} ({e})")
        return report

    # --- internals --------------------------------------------------------
    def _select_queue(self, discovered: list[str], *, force: bool, limit: int | None) -> list[str]:
        queue: list[str] = []
        # include discovered URLs + any previously-discovered not-yet-fetched
        candidates = list(discovered)
        if not force:
            extra = self.db.conn.execute(
                "SELECT canonical_url FROM documents WHERE status IN ('discovered','queued','error')"
            ).fetchall()
            candidates.extend(r["canonical_url"] for r in extra)
        seen = set()
        for url in candidates:
            c = url if url.startswith("http") else _abs(self.cfg, url)
            if c in seen:
                continue
            seen.add(c)
            if not force:
                row = self.db.conn.execute(
                    "SELECT status FROM documents WHERE canonical_url = ?", (c,)
                ).fetchone()
                if row and row["status"] in ("parsed", "unchanged"):
                    continue
            queue.append(c)
            if limit and len(queue) >= limit:
                break
        return queue

    def _fetch_parse_store(self, url: str, report: CrawlReport) -> None:
        res = self.http.fetch(url)
        report.fetched += 1
        charset = _charset(res.content_type)
        parsed = parse_page(url, res.content, charset=charset)

        # filter by page type
        if parsed.page_type not in self.cfg.fetch_page_types:
            self.db.conn.execute(
                "UPDATE documents SET status='skipped', last_checked_at=?, page_type=? WHERE canonical_url=?",
                (self.db.now(), parsed.page_type, url),
            )
            self.db.conn.commit()
            report.skipped += 1
            return

        doc = _parsed_to_document_in(url, parsed)
        _, action = store.upsert_document(
            self.db, doc,
            html_bytes=res.content if self.cfg.store_html else None,
            archive_root=self.cfg.archive_dir,
        )
        if action == "unchanged":
            report.unchanged += 1
        else:
            report.parsed += 1

        # --- frameset follow-through ---------------------------------------
        # A frameset page has no content of its own; the real text lives in
        # its inner <frame> documents. After storing the frameset, fetch each
        # inner frame (within the page cap) and store it as its own document,
        # linked back to the frameset via source_metadata.parent_frameset_url.
        if parsed.page_type == "frameset" and parsed.frames:
            for fr in parsed.frames:
                # respect the per-run page cap
                if self.http._pages_this_run >= self.cfg.max_pages_per_run:
                    parsed.warnings.append(
                        f"frameset inner frame not fetched (cap reached): {fr.src}"
                    )
                    break
                try:
                    self._fetch_parse_store_inner(fr, parent_url=url, report=report)
                except Exception as e:  # noqa: BLE001
                    report.errors += 1
                    report.error_urls.append(f"{fr.src} (inner frame: {e})")

    def _fetch_parse_store_inner(self, frame, *, parent_url: str, report: CrawlReport) -> None:
        """Fetch a <frame> src discovered inside a frameset page and store it
        as its own document, linked back to the parent frameset."""
        res = self.http.fetch(frame.src)
        report.fetched += 1
        charset = _charset(res.content_type)
        parsed = parse_page(frame.src, res.content, charset=charset)
        if parsed.page_type not in self.cfg.fetch_page_types:
            report.skipped += 1
            return
        doc = _parsed_to_document_in(frame.src, parsed)
        # link the inner frame back to its parent frameset
        meta = dict(doc.source_metadata or {})
        meta["parent_frameset_url"] = parent_url
        meta["frame_role"] = frame.role
        doc.source_metadata = meta
        _, action = store.upsert_document(
            self.db, doc,
            html_bytes=res.content if self.cfg.store_html else None,
            archive_root=self.cfg.archive_dir,
        )
        if action == "unchanged":
            report.unchanged += 1
        else:
            report.parsed += 1


def _abs(cfg: Config, url: str) -> str:
    if url.startswith("http"):
        return url
    from urllib.parse import urljoin
    return urljoin(cfg.base_url, url)


def _charset(content_type: str) -> str | None:
    if "charset=" in (content_type or "").lower():
        return content_type.split("charset=", 1)[1].split(";")[0].strip()
    return "windows-1251"


def _parsed_to_document_in(url: str, p: ParsedPage) -> DocumentIn:
    sections: list[SectionIn] = []
    for i, s in enumerate(p.sections, 1):
        sections.append(SectionIn(
            section_type=s.section_type,  # type: ignore[arg-type]
            heading=s.heading,
            text=s.text,
            sequence_number=i,
            page_number=s.page_number,
            anchor=s.anchor,
            source_url=s.source_url or url,
        ))
    meta = dict(p.source_metadata)
    meta["parser_warnings"] = p.warnings
    meta["images"] = [{"url": im.url, "label": im.label, "size": im.size_note} for im in p.images]
    meta["links"] = [{"url": lk.url, "label": lk.label, "kind": lk.kind} for lk in p.links]
    return DocumentIn(
        canonical_url=url,
        page_type=p.page_type,
        title=p.title,
        author=p.author,
        translator=p.translator,
        editor=p.editor,
        original_creation_date=p.original_creation_date,
        publication_year=p.publication_year,
        publication_title=p.publication_title,
        source_type=p.source_type,
        language=p.language,
        region=p.region,
        collection=p.collection,
        description=p.description,
        bibliography=p.bibliography,
        source_metadata=meta,
        extracted_text=p.extracted_text,
        extraction_method=p.extraction_method,
        extraction_warnings=p.warnings,
        sections=sections,
    )
