"""Low-level FTS5 query helpers.

Kept separate from engine.py so the SQL is auditable in one place. All FTS
columns hold NORMALISED text (see textnorm.normalise_search), so queries must
be normalised the same way before MATCH.
"""

from __future__ import annotations

from .. import textnorm


def fts_match_sections(conn, query: str, limit: int = 100) -> list[dict]:
    """Full-text search over section body+heading. Returns raw FTS rows."""
    q = textnorm.build_fts_query(query)
    if not q:
        return []
    rows = conn.execute(
        """
        SELECT s.document_id AS document_id,
               s.section_id  AS section_id,
               bm25(fts_sections) AS score
        FROM fts_sections s
        WHERE fts_sections MATCH ?
        ORDER BY bm25(fts_sections)
        LIMIT ?
        """,
        (q, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fts_match_documents(conn, query: str, limit: int = 100) -> list[dict]:
    """Full-text search over document metadata (title/author/region/...)."""
    q = textnorm.build_fts_query(query)
    if not q:
        return []
    rows = conn.execute(
        """
        SELECT document_id, bm25(fts_documents) AS score
        FROM fts_documents
        WHERE fts_documents MATCH ?
        ORDER BY bm25(fts_documents)
        LIMIT ?
        """,
        (q, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fts_match_name_variants(conn, query: str, limit: int = 100) -> list[dict]:
    q = textnorm.build_fts_query(query)
    if not q:
        return []
    rows = conn.execute(
        """
        SELECT variant_id, entity_id, bm25(fts_name_variants) AS score
        FROM fts_name_variants
        WHERE fts_name_variants MATCH ?
        ORDER BY bm25(fts_name_variants)
        LIMIT ?
        """,
        (q, limit),
    ).fetchall()
    return [dict(r) for r in rows]
