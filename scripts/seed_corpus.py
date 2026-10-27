#!/usr/bin/env python3
"""Seed the local DB from the verified test fixtures (real Vostlit pages).

This imports the 13 fixture pages saved during the site audit (see
tests/fixtures/fixtures_manifest.json) so the system has REAL searchable
content offline, without re-hitting the site. It also adds a small set of
curated entities / name-variants that are explicitly grounded in the fixture
text (each marked with its verification status — none are invented).

Usage:
    python3 scripts/seed_corpus.py [--db DATA/vostlit.db]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vostlit_research.config import Config, load_config
from vostlit_research.db import Database
from vostlit_research.collector.parser import parse_page
from vostlit_research.collector.crawl import _parsed_to_document_in
from vostlit_research import store
from vostlit_research.io import upsert_entity, upsert_name_variant
from vostlit_research.models import EntityIn, NameVariantIn

FIXTURES = ROOT / "tests" / "fixtures"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    args = ap.parse_args()
    cfg = load_config()  # applies VOSTLIT_* env vars
    if args.db:
        cfg.db_path = Path(args.db)
    cfg.ensure_dirs()
    db = Database(cfg.db_path)

    manifest = json.loads((FIXTURES / "fixtures_manifest.json").read_text(encoding="utf-8"))
    n_docs = 0
    for f in manifest["fixtures"]:
        raw = (FIXTURES / f["filename"]).read_bytes()
        url = f["source_url"]
        parsed = parse_page(url, raw, charset="windows-1251")
        # only store content-bearing page types
        if parsed.page_type not in ("document_text", "notes_page", "image_gallery",
                                    "collection_index", "alpha_index", "region_catalog"):
            continue
        doc = _parsed_to_document_in(url, parsed)
        # tag region for caucasus/dagestan-relevant docs (grounded in URL/path)
        if "/Kavkaz/" in url or "/Dokumenty/kavkaz" in url or "Dag_chron" in url:
            doc.region = "Кавказ"
        if "Dagestan" in url or "Dag_chron" in url or "Дагестан" in (parsed.title or ""):
            doc.region = "Дагестан"
        store.upsert_document(db, doc, html_bytes=raw if cfg.store_html else None,
                              archive_root=cfg.archive_dir)
        n_docs += 1
    print(f"imported {n_docs} documents from fixtures")

    # --- curated entities grounded in the fixture text --------------------
    # Each entity/variant below is attested in the imported corpus; statuses
    # are honest (candidate where identification is not certain).
    entities = [
        EntityIn(canonical_name="Дагестан", entity_type="place",
                 description="Историко-географическая область на Северо-Восточном Кавказе.",
                 confidence="verified"),
        EntityIn(canonical_name="Кавказ", entity_type="place",
                 description="Горная область между Чёрным и Каспийским морями.",
                 confidence="verified"),
        EntityIn(canonical_name="Гумбет", entity_type="society",
                 description="Историческое горное общество (вольное общество) в Дагестане.",
                 confidence="verified"),
        EntityIn(canonical_name="Салатавия", entity_type="society",
                 description="Историческое общество в Дагестане, сосед Гумбета.",
                 confidence="verified"),
        EntityIn(canonical_name="Дербенд-наме", entity_type="work",
                 description="Дагестанское историческое сочинение о Дербенте.",
                 confidence="verified"),
    ]
    eid_map = {}
    for e in entities:
        eid_map[e.canonical_name] = upsert_entity(db, e)

    variants = [
        NameVariantIn(entity_id=eid_map["Дагестан"], original_form="Дагестанъ",
                      variant_type="historical", language="ru",
                      verification_status="candidate"),
        NameVariantIn(entity_id=eid_map["Гумбет"], original_form="Гумбетъ",
                      variant_type="historical", language="ru",
                      verification_status="candidate"),
        NameVariantIn(entity_id=eid_map["Салатавия"], original_form="Салатавія",
                      variant_type="historical", language="ru",
                      verification_status="candidate"),
        NameVariantIn(entity_id=eid_map["Салатавия"], original_form="Салатав",
                      variant_type="transliteration", language="ru",
                      verification_status="candidate"),
    ]
    for v in variants:
        upsert_name_variant(db, v)

    st = db.stats()
    print(f"corpus: {st['documents']} docs, {st['document_sections']} sections, "
          f"{st['entities']} entities, {st['name_variants']} variants")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
