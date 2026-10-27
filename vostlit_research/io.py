"""JSONL import/export for vostlit_research.

The JSONL format is the canonical, human-auditable transfer format. Each line
is one JSON object matching :class:`DocumentIn` (for documents) — or, in a
mixed stream, objects with a ``"kind"`` field (``document`` | ``entity`` |
``name_variant`` | ``research_note``). The importer dispatches on ``kind``.

This is the ONLY format used for corpus transfer. It is deliberately
line-delimited so it streams and diffs cleanly under git.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .db import Database
from .models import (
    DocumentIn, EntityIn, NameVariantIn, ResearchNoteIn,
)
from . import textnorm
from . import store as _store


def _iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{ln}: invalid JSON: {e}") from e


def import_jsonl(
    db: Database, path: str | Path, *, archive_root=None
) -> dict[str, int]:
    counts = {"documents": 0, "entities": 0, "name_variants": 0,
              "research_notes": 0, "errors": 0, "created": 0,
              "updated": 0, "unchanged": 0}
    for obj in _iter_jsonl(path):
        kind = obj.get("kind", "document")
        try:
            if kind == "document":
                rec = DocumentIn.model_validate(obj)
                _, action = _store.upsert_document(db, rec, archive_root=archive_root)
                counts["documents"] += 1
                counts[action] = counts.get(action, 0) + 1
            elif kind == "entity":
                upsert_entity(db, EntityIn.model_validate(obj))
                counts["entities"] += 1
            elif kind == "name_variant":
                upsert_name_variant(db, NameVariantIn.model_validate(obj))
                counts["name_variants"] += 1
            elif kind == "research_note":
                upsert_research_note(db, ResearchNoteIn.model_validate(obj))
                counts["research_notes"] += 1
            else:
                counts["errors"] += 1
        except Exception as e:  # noqa: BLE001
            counts["errors"] += 1
            db.conn.execute(
                "INSERT INTO crawl_log(url, canonical_url, action, detail, fetched_at) VALUES (?,?,?,?,?)",
                ("(jsonl)", "(jsonl)", "error", f"{kind}: {e}", db.now()),
            )
            db.conn.commit()
    return counts


def export_jsonl(db: Database, path: str | Path, *, include_sections: bool = True) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for r in db.conn.execute("SELECT id FROM documents ORDER BY id"):
            d = _store.document_to_export_dict(db, r["id"])
            if d is None:
                continue
            if not include_sections:
                d.pop("sections", None)
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
        for r in db.conn.execute("SELECT id FROM entities ORDER BY id"):
            e = db.conn.execute("SELECT * FROM entities WHERE id = ?", (r["id"],)).fetchone()
            fh.write(json.dumps({
                "kind": "entity",
                "canonical_name": e["canonical_name"],
                "entity_type": e["entity_type"],
                "description": e["description"],
                "earliest_attested_date": e["earliest_attested_date"],
                "latest_attested_date": e["latest_attested_date"],
                "confidence": e["confidence"],
                "notes": e["notes"],
            }, ensure_ascii=False) + "\n")
            n += 1
        for r in db.conn.execute("SELECT id FROM name_variants ORDER BY id"):
            v = db.conn.execute("SELECT * FROM name_variants WHERE id = ?", (r["id"],)).fetchone()
            fh.write(json.dumps({
                "kind": "name_variant",
                "entity_id": v["entity_id"],
                "original_form": v["original_form"],
                "normalized_form": v["normalized_form"],
                "language": v["language"],
                "script": v["script"],
                "transliteration_system": v["transliteration_system"],
                "variant_type": v["variant_type"],
                "date_range": v["date_range"],
                "confidence": v["confidence"],
                "verification_status": v["verification_status"],
            }, ensure_ascii=False) + "\n")
            n += 1
    return n


# ---------------------------------------------------------------------- aux upserts

def upsert_entity(db: Database, e: EntityIn) -> int:
    with db.conn:
        row = db.conn.execute(
            "SELECT id FROM entities WHERE canonical_name = ? AND entity_type = ?",
            (e.canonical_name, e.entity_type),
        ).fetchone()
        if row:
            db.conn.execute(
                """UPDATE entities SET description=COALESCE(?,description),
                   earliest_attested_date=COALESCE(?,earliest_attested_date),
                   latest_attested_date=COALESCE(?,latest_attested_date),
                   confidence=COALESCE(?,confidence), notes=COALESCE(?,notes) WHERE id=?""",
                (e.description, e.earliest_attested_date, e.latest_attested_date,
                 e.confidence, e.notes, row["id"]),
            )
            eid = int(row["id"])
        else:
            cur = db.conn.execute(
                """INSERT INTO entities (canonical_name, entity_type, description,
                   earliest_attested_date, latest_attested_date, confidence, notes)
                   VALUES (?,?,?,?,?,?,?)""",
                (e.canonical_name, e.entity_type, e.description,
                 e.earliest_attested_date, e.latest_attested_date, e.confidence, e.notes),
            )
            eid = int(cur.lastrowid)
    db.reindex_entity(eid)
    return eid


def upsert_name_variant(db: Database, v: NameVariantIn) -> int:
    eid = v.entity_id
    if eid is None and v.canonical_name:
        # look up or create entity by canonical_name + type
        with db.conn:
            row = db.conn.execute(
                "SELECT id FROM entities WHERE canonical_name = ? AND COALESCE(entity_type,'') = COALESCE(?,'')",
                (v.canonical_name, v.entity_type or ""),
            ).fetchone()
            if row:
                eid = int(row["id"])
            else:
                cur = db.conn.execute(
                    "INSERT INTO entities (canonical_name, entity_type) VALUES (?,?)",
                    (v.canonical_name, v.entity_type or "place"),
                )
                eid = int(cur.lastrowid)
        db.reindex_entity(eid)
    norm = textnorm.normalise_search(v.original_form)
    with db.conn:
        cur = db.conn.execute(
            """INSERT INTO name_variants
               (entity_id, original_form, normalized_form, language, script,
                transliteration_system, variant_type, date_range,
                evidence_section_id, confidence, verification_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (eid, v.original_form, norm, v.language, v.script,
             v.transliteration_system, v.variant_type, v.date_range,
             v.evidence_section_id, v.confidence, v.verification_status),
        )
        vid = int(cur.lastrowid)
    db.reindex_name_variant(vid)
    return vid


def upsert_research_note(db: Database, n: ResearchNoteIn) -> int:
    import json as _json
    with db.conn:
        cur = db.conn.execute(
            """INSERT INTO research_notes
               (claim, status, supporting_fragments, contradicting_fragments,
                argumentation, author_or_mechanism, created_at, confidence, change_history)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (n.claim, n.status,
             _json.dumps([f.model_dump() for f in n.supporting_fragments], ensure_ascii=False),
             _json.dumps([f.model_dump() for f in n.contradicting_fragments], ensure_ascii=False),
             n.argumentation, n.author_or_mechanism, db.now(), n.confidence, "[]"),
        )
        return int(cur.lastrowid)
