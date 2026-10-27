"""Writing documents into the database, with de-duplication and versioning.

This module is the single chokepoint used by BOTH the JSONL importer and the
live-site collector. Guarantees:

  * Re-importing the same URL never creates a duplicate document (matched on
    ``canonical_url``).
  * Re-importing with identical extracted_text does not create a new version
    (matched on ``content_hash``); ``documents.status`` becomes ``unchanged``.
  * Changed text creates a NEW immutable version; the old version + its
    sections are retained so a research note can still point at the exact
    version of the text it was made against.
  * FTS5 indexes are re-synced for the document after every write.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from . import archive, textnorm
from .db import Database
from .models import DocumentIn, SectionIn

PARSER_VERSION = "vostlit-research/0.1.0"


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def upsert_document(
    db: Database,
    doc: DocumentIn,
    *,
    html_bytes: bytes | None = None,
    archive_root=None,
    now: str | None = None,
) -> tuple[int, str]:
    """Insert or update a document. Returns ``(document_id, action)`` where
    action is one of ``created`` / ``updated`` / ``unchanged`` / ``metadata``.
    """
    now = now or db.now()
    canonical = textnorm.normalise_url(doc.canonical_url)
    if not canonical:
        raise ValueError("Document has no canonical_url")
    stable_id = doc.stable_id or textnorm.stable_id_from_url(canonical)

    meta_json = json.dumps(doc.source_metadata, ensure_ascii=False) if doc.source_metadata else None
    extracted = doc.extracted_text or ""
    content_hash = _sha(extracted) if extracted else None

    with db.conn:
        row = db.conn.execute(
            "SELECT id, current_version_id, content_hash FROM documents WHERE canonical_url = ?",
            (canonical,),
        ).fetchone()

        # ---- metadata upsert ------------------------------------------------
        if row is None:
            cur = db.conn.execute(
                """
                INSERT INTO documents
                  (canonical_url, stable_id, page_type, title, author, translator, editor,
                   original_creation_date, publication_year, publication_title, source_type,
                   language, region, collection, description, bibliography, source_metadata_json,
                   first_seen_at, last_checked_at, retrieved_at, content_hash, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (canonical, stable_id, doc.page_type, doc.title, doc.author,
                 doc.translator, doc.editor, doc.original_creation_date,
                 doc.publication_year, doc.publication_title, doc.source_type,
                 doc.language, doc.region, doc.collection, doc.description,
                 doc.bibliography, meta_json, now, now,
                 now if extracted else None, content_hash,
                 "fetched" if extracted else "discovered"),
            )
            doc_id = int(cur.lastrowid)
            action = "created"
        else:
            doc_id = int(row["id"])
            db.conn.execute(
                """
                UPDATE documents SET
                  stable_id = COALESCE(?, stable_id),
                  page_type = COALESCE(?, page_type),
                  title = COALESCE(?, title),
                  author = COALESCE(?, author),
                  translator = COALESCE(?, translator),
                  editor = COALESCE(?, editor),
                  original_creation_date = COALESCE(?, original_creation_date),
                  publication_year = COALESCE(?, publication_year),
                  publication_title = COALESCE(?, publication_title),
                  source_type = COALESCE(?, source_type),
                  language = COALESCE(?, language),
                  region = COALESCE(?, region),
                  collection = COALESCE(?, collection),
                  description = COALESCE(?, description),
                  bibliography = COALESCE(?, bibliography),
                  source_metadata_json = COALESCE(?, source_metadata_json),
                  last_checked_at = ?
                WHERE id = ?
                """,
                (stable_id, doc.page_type, doc.title, doc.author, doc.translator,
                 doc.editor, doc.original_creation_date, doc.publication_year,
                 doc.publication_title, doc.source_type, doc.language, doc.region,
                 doc.collection, doc.description, doc.bibliography, meta_json, now, doc_id),
            )
            action = "updated"

        # ---- versioning -----------------------------------------------------
        version_id: int | None = None
        if extracted:
            # has the text actually changed?
            prev = db.conn.execute(
                "SELECT content_hash FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if prev["content_hash"] == content_hash and row is not None:
                # unchanged: keep current version
                version_id = row["current_version_id"]
                action = "unchanged" if action != "created" else action
                db.conn.execute(
                    "UPDATE documents SET status = 'unchanged', retrieved_at = ? WHERE id = ?",
                    (now, doc_id),
                )
            else:
                # archive HTML, then create a new version
                html_rel: str | None = None
                if html_bytes and archive_root is not None:
                    _, rel = archive.store(archive_root, html_bytes, suffix=".html")
                    html_rel = str(rel)
                vnum_row = db.conn.execute(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 AS vn FROM document_versions WHERE document_id = ?",
                    (doc_id,),
                ).fetchone()
                vnum = int(vnum_row["vn"])
                warnings_json = json.dumps(
                    doc.extraction_warnings or [], ensure_ascii=False
                ) if doc.extraction_warnings else None
                cur = db.conn.execute(
                    """
                    INSERT INTO document_versions
                      (document_id, version_number, extracted_text, original_html_path,
                       extraction_method, extracted_at, content_hash, parser_version,
                       extraction_warnings)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (doc_id, vnum, extracted, html_rel, doc.extraction_method,
                     now, content_hash, PARSER_VERSION, warnings_json),
                )
                version_id = int(cur.lastrowid)
                db.conn.execute(
                    "UPDATE documents SET current_version_id = ?, content_hash = ?, retrieved_at = ?, status = 'parsed' WHERE id = ?",
                    (version_id, content_hash, now, doc_id),
                )
                action = "created" if action == "created" else "updated"

        # ---- sections -------------------------------------------------------
        if doc.sections and version_id is not None:
            # sections belong to this version; clear any prior sections for THIS version
            db.conn.execute(
                "DELETE FROM document_sections WHERE document_version_id = ?", (version_id,)
            )
            for i, s in enumerate(doc.sections):
                db.conn.execute(
                    """
                    INSERT INTO document_sections
                      (document_version_id, document_id, section_type, heading, text, text_lower,
                       sequence_number, page_number, anchor, source_url)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (version_id, doc_id, s.section_type, s.heading, s.text,
                     textnorm.lower_cyr(s.text or "") if s.text else None,
                     s.sequence_number, s.page_number, s.anchor, s.source_url),
                )

    # FTS sync (outside the write transaction is fine; reindex opens its own)
    db.reindex_document(doc_id)
    return doc_id, action


# ---------------------------------------------------------------------- bulk

def import_document_records(
    db: Database, records: list[DocumentIn], *, archive_root=None
) -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "errors": 0}
    for rec in records:
        try:
            _, action = upsert_document(db, rec, archive_root=archive_root)
            counts[action] = counts.get(action, 0) + 1
        except Exception as e:  # noqa: BLE001
            counts["errors"] += 1
            db.conn.execute(
                "INSERT INTO crawl_log(url, canonical_url, action, detail, fetched_at) VALUES (?,?,?,?,?)",
                (rec.canonical_url, textnorm.normalise_url(rec.canonical_url), "error", str(e), db.now()),
            )
            db.conn.commit()
    return counts


def document_to_export_dict(db: Database, document_id: int) -> dict[str, Any] | None:
    """Serialise a document + its current version + sections to a plain dict."""
    doc = db.conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if doc is None:
        return None
    ver = db.conn.execute(
        "SELECT * FROM document_versions WHERE id = ?", (doc["current_version_id"],)
    ).fetchone() if doc["current_version_id"] else None
    sections = []
    if ver:
        for s in db.conn.execute(
            "SELECT * FROM document_sections WHERE document_version_id = ? ORDER BY sequence_number",
            (ver["id"],),
        ).fetchall():
            sections.append({
                "section_type": s["section_type"],
                "heading": s["heading"],
                "text": s["text"],
                "sequence_number": s["sequence_number"],
                "page_number": s["page_number"],
                "anchor": s["anchor"],
                "source_url": s["source_url"],
            })
    return {
        "canonical_url": doc["canonical_url"],
        "stable_id": doc["stable_id"],
        "page_type": doc["page_type"],
        "title": doc["title"],
        "author": doc["author"],
        "translator": doc["translator"],
        "editor": doc["editor"],
        "original_creation_date": doc["original_creation_date"],
        "publication_year": doc["publication_year"],
        "publication_title": doc["publication_title"],
        "source_type": doc["source_type"],
        "language": doc["language"],
        "region": doc["region"],
        "collection": doc["collection"],
        "description": doc["description"],
        "bibliography": doc["bibliography"],
        "source_metadata": json.loads(doc["source_metadata_json"]) if doc["source_metadata_json"] else None,
        "extracted_text": ver["extracted_text"] if ver else None,
        "extraction_method": ver["extraction_method"] if ver else None,
        "extraction_warnings": json.loads(ver["extraction_warnings"]) if ver and ver["extraction_warnings"] else None,
        "content_hash": ver["content_hash"] if ver else None,
        "parser_version": ver["parser_version"] if ver else None,
        "sections": sections,
    }
