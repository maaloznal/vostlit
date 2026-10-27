"""SQLite layer: connection, schema bootstrap, migrations, FTS5 sync.

The database is a single file (default ``data/vostlit.db``). All access goes
through :class:`Database`, which opens the connection with the right pragmas
and ensures the schema is at the latest version.

FTS5 indexes are kept in sync EXPLICITLY by the writer methods on this class
(``reindex_document`` etc.) rather than via triggers, because the indexed text
is a NORMALISED derivative of the original (see textnorm) and triggers over
normalised columns would duplicate logic in SQL. Explicit sync also makes the
"rebuild from scratch" path obvious and testable.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import textnorm

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 1


def _now() -> str:
    # ISO 8601, local-ish but timezone-explicit. We store naive UTC for
    # portability; the CLI formats for display in Europe/Moscow when needed.
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class Database:
    """A thin wrapper around sqlite3.Connection with schema management."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._ensure_schema()

    # --- lifecycle --------------------------------------------------------
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # --- schema -----------------------------------------------------------
    def _ensure_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            row = self.conn.execute(
                "SELECT MAX(version) AS v FROM schema_version"
            ).fetchone()
            current = row["v"] if (row and row["v"] is not None) else 0
            if current < SCHEMA_VERSION:
                self.conn.execute(
                    "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _now()),
                )

    def schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
        return int(row["v"]) if (row and row["v"] is not None) else 0

    def fts5_available(self) -> bool:
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)"
            )
            self.conn.execute("DROP TABLE IF EXISTS _fts5_probe")
            return True
        except sqlite3.OperationalError:
            return False

    # --- low-level helpers ------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def commit(self) -> None:
        self.conn.commit()

    def now(self) -> str:
        return _now()

    # --- FTS5 sync --------------------------------------------------------
    def reindex_document(self, document_id: int) -> None:
        """Rewrite all FTS rows for one document from the canonical tables.

        Idempotent: deletes then re-inserts. Safe to call after any change to
        a document's metadata, versions or sections.
        """
        with self.conn:
            self.conn.execute(
                "DELETE FROM fts_documents WHERE document_id = ?", (document_id,)
            )
            self.conn.execute(
                "DELETE FROM fts_sections WHERE document_id = ?", (document_id,)
            )
            doc = self.conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if doc is None:
                return
            self.conn.execute(
                """
                INSERT INTO fts_documents
                  (title_norm, author_norm, translator_norm, editor_norm,
                   publication_title, region_norm, collection_norm,
                   description_norm, bibliography_norm, document_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    textnorm.normalise_search(doc["title"] or ""),
                    textnorm.normalise_search(doc["author"] or ""),
                    textnorm.normalise_search(doc["translator"] or ""),
                    textnorm.normalise_search(doc["editor"] or ""),
                    doc["publication_title"] or "",
                    textnorm.normalise_search(doc["region"] or ""),
                    textnorm.normalise_search(doc["collection"] or ""),
                    textnorm.normalise_search(doc["description"] or ""),
                    textnorm.normalise_search(doc["bibliography"] or ""),
                    document_id,
                ),
            )
            sections = self.conn.execute(
                "SELECT id, heading, text FROM document_sections WHERE document_id = ?",
                (document_id,),
            ).fetchall()
            for s in sections:
                self.conn.execute(
                    """
                    INSERT INTO fts_sections (heading_norm, text_norm, document_id, section_id)
                    VALUES (?,?,?,?)
                    """,
                    (
                        textnorm.normalise_search(s["heading"] or ""),
                        textnorm.normalise_search(s["text"] or ""),
                        document_id,
                        s["id"],
                    ),
                )

    def reindex_name_variant(self, variant_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM fts_name_variants WHERE variant_id = ?", (variant_id,)
            )
            v = self.conn.execute(
                "SELECT id, entity_id, original_form, normalized_form FROM name_variants WHERE id = ?",
                (variant_id,),
            ).fetchone()
            if v is None:
                return
            self.conn.execute(
                """
                INSERT INTO fts_name_variants
                  (original_norm, normalized_form, entity_id, variant_id)
                VALUES (?,?,?,?)
                """,
                (
                    textnorm.normalise_search(v["original_form"] or ""),
                    v["normalized_form"] or "",
                    v["entity_id"],
                    v["id"],
                ),
            )

    def reindex_entity(self, entity_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM fts_entities WHERE entity_id = ?", (entity_id,)
            )
            e = self.conn.execute(
                "SELECT id, canonical_name, description FROM entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if e is None:
                return
            self.conn.execute(
                "INSERT INTO fts_entities (canonical_name, description, entity_id) VALUES (?,?,?)",
                (e["canonical_name"] or "", e["description"] or "", entity_id),
            )

    def rebuild_all_fts(self) -> dict[str, int]:
        """Drop and rebuild every FTS index from the canonical tables.

        Returns counts of the rows written.
        """
        with self.conn:
            for t in ("fts_sections", "fts_documents", "fts_name_variants", "fts_entities"):
                self.conn.execute(f"DELETE FROM {t}")
            docs = self.conn.execute("SELECT id FROM documents").fetchall()
            for d in docs:
                # inline reindex (we are already in a transaction)
                self.conn.execute(
                    "DELETE FROM fts_documents WHERE document_id = ?", (d["id"],)
                )
                self.conn.execute(
                    "DELETE FROM fts_sections WHERE document_id = ?", (d["id"],)
                )
                doc = self.conn.execute(
                    "SELECT * FROM documents WHERE id = ?", (d["id"],)
                ).fetchone()
                self.conn.execute(
                    """
                    INSERT INTO fts_documents
                      (title_norm, author_norm, translator_norm, editor_norm,
                       publication_title, region_norm, collection_norm,
                       description_norm, bibliography_norm, document_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        textnorm.normalise_search(doc["title"] or ""),
                        textnorm.normalise_search(doc["author"] or ""),
                        textnorm.normalise_search(doc["translator"] or ""),
                        textnorm.normalise_search(doc["editor"] or ""),
                        doc["publication_title"] or "",
                        textnorm.normalise_search(doc["region"] or ""),
                        textnorm.normalise_search(doc["collection"] or ""),
                        textnorm.normalise_search(doc["description"] or ""),
                        textnorm.normalise_search(doc["bibliography"] or ""),
                        doc["id"],
                    ),
                )
                for s in self.conn.execute(
                    "SELECT id, heading, text FROM document_sections WHERE document_id = ?",
                    (d["id"],),
                ).fetchall():
                    self.conn.execute(
                        "INSERT INTO fts_sections (heading_norm, text_norm, document_id, section_id) VALUES (?,?,?,?)",
                        (
                            textnorm.normalise_search(s["heading"] or ""),
                            textnorm.normalise_search(s["text"] or ""),
                            d["id"],
                            s["id"],
                        ),
                    )
            for v in self.conn.execute(
                "SELECT id, entity_id, original_form, normalized_form FROM name_variants"
            ).fetchall():
                self.conn.execute(
                    "INSERT INTO fts_name_variants (original_norm, normalized_form, entity_id, variant_id) VALUES (?,?,?,?)",
                    (
                        textnorm.normalise_search(v["original_form"] or ""),
                        v["normalized_form"] or "",
                        v["entity_id"],
                        v["id"],
                    ),
                )
            for e in self.conn.execute(
                "SELECT id, canonical_name, description FROM entities"
            ).fetchall():
                self.conn.execute(
                    "INSERT INTO fts_entities (canonical_name, description, entity_id) VALUES (?,?,?)",
                    (e["canonical_name"] or "", e["description"] or "", e["id"]),
                )
        return {
            "documents": len(docs),
            "variants": self.conn.execute("SELECT COUNT(*) c FROM name_variants").fetchone()["c"],
            "entities": self.conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"],
        }

    # --- stats ------------------------------------------------------------
    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in (
            "documents", "document_versions", "document_sections", "entities",
            "name_variants", "mentions", "research_notes", "crawl_log",
        ):
            out[t] = self.conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        out["documents_by_status"] = {
            r["status"]: r["c"]
            for r in self.conn.execute(
                "SELECT status, COUNT(*) c FROM documents GROUP BY status"
            ).fetchall()
        }
        out["documents_by_type"] = {
            r["page_type"] or "(none)": r["c"]
            for r in self.conn.execute(
                "SELECT page_type, COUNT(*) c FROM documents GROUP BY page_type"
            ).fetchall()
        }
        return out


def connect(path: str | Path) -> Database:
    return Database(path)


# Re-exported for convenience in the CLI/tests.
def dump_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
