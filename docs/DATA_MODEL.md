# Data Model

The schema lives in `vostlit_research/schema.sql` and is versioned via the
`schema_version` table (currently version 1). This document explains the
*intent* of each table. For column-level detail, read the SQL — it is the
source of truth and is heavily commented.

## Entity-relationship overview

```
documents 1───* document_versions 1───* document_sections
    │                │
    │                └──(evidence)──┐
    │                                │
    │  entities 1───* name_variants ─┘
    │      │            │
    │      │            └──(evidence_section_id)
    │      │
    │  entities 1───* mentions ─── documents / document_sections
    │
    └──(supporting/contradicting fragments, JSON)── research_notes

FTS5 (derived, kept in sync by db.reindex_*):
  fts_documents   <- documents (metadata)
  fts_sections    <- document_sections (body+heading)
  fts_name_variants <- name_variants
  fts_entities    <- entities

crawl_log        <- every URL touched (audit/resume)
```

## documents
One row per discovered source page, de-duplicated by `canonical_url`
(normalised: https, lowercased host, only the `id` query kept). Carries the
bibliographic metadata (title, author, translator, editor, dates, region,
collection, bibliography) and the *current* version pointer. `status` cycles:
`discovered → fetched/parsed → unchanged` (or `skipped`/`error`).

## document_versions
Immutable snapshots of extracted content. A new row is created only when
`content_hash` (sha256 of `extracted_text`) changes. Stores the
`original_html_path` (relative to the archive root, or NULL), the parser
branch used, the parser version, and any `extraction_warnings` (JSON).

## document_sections
Structured parts of a version, in document order (`sequence_number`).
`section_type` ∈ {body, heading, footnote, note, bibliography, caption,
page_break, chapter_marker}. Keeps the ORIGINAL `text` AND a Cyrillic-aware
`text_lower` copy (for case-insensitive exact matching that preserves ё).
`page_number` is set for `page_break` sections; `anchor` holds note numbers
for `note` sections.

## entities
Canonical historical entities: person, place, settlement, society, state,
ethnonym, organisation, event, work. `confidence` is a categorical
(verified/probable/possible) — never a fake percentage.

## name_variants
Spellings of an entity, each with provenance: `original_form` (verbatim),
`normalized_form` (search-normalised), language/script/transliteration,
`variant_type`, a date range, an `evidence_section_id` pointing at the
section where the spelling is attested, and a `verification_status`. A
variant with no evidence section is a dictionary entry, not a corpus
attestation.

## mentions
Links an entity/name-variant to a document+section with the exact
`mention_text` and surrounding `context_before`/`context_after`. Supports
manual curation and (future) automatic extraction. `verification_status`
keeps candidates distinct from confirmed mentions.

## research_notes
Investigator conclusions, kept STRICTLY separate from source text. `status`
∈ {source_fact, interpretation, hypothesis, refuted}. `supporting_fragments`
and `contradicting_fragments` are JSON lists of {section_id, quote, url}. A
hypothesis can never silently become a source_fact — the `change_history`
JSON records every transition.

## FTS5 indexes
All FTS5 tables index NORMALISED text (`textnorm.normalise_search`:
NFKC → pre-reform fold → ё fold → lower → punct→space → collapse). This
makes search ё-insensitive and pre-reform-insensitive. The ORIGINAL text
lives in the base tables; FTS only holds the derivative. `UNINDEXED` id
columns let results map back to real rows. Sync is explicit
(`reindex_document` / `reindex_name_variant` / `reindex_entity` /
`rebuild_all_fts`).

## crawl_log
Append-only audit of every URL the collector has touched: `action` ∈
{discovered, fetched, parsed, skipped, error}. Powers resume (skip already-
parsed) and the audit trail.

## Migrations
`schema_version` table holds the applied version. `_ensure_schema` runs the
DDL (all `CREATE TABLE IF NOT EXISTS`) on every open and records the version
if newer. Future migrations: bump `SCHEMA_VERSION`, add a migration block.
