# SCHEMA AUDIT — vostlit_research SQLite schema (v1)

> Task ID: **B-schema** · Agent: knowledge-architect
> Date: 2025-10-27 (Europe/Moscow)
> Scope: audit `vostlit_research/schema.sql` (schema_version = 1) for its
> ability to model historical knowledge with provenance. Audit only — no
> code or schema changes performed.
> Companion files: `docs/DATA_MODEL.md`, `docs/UPGRADE_BASELINE.md`,
> `vostlit_research/schema.sql`, `vostlit_research/store.py`,
> `vostlit_research/db.py`, `vostlit_research/io.py`,
> `vostlit_research/cli.py`, `vostlit_research/models.py`,
> `vostlit_research/research/api.py`, `vostlit_research/search/engine.py`.

---

## 1. Method

The audit was performed by reading the following files end-to-end and
cross-referencing DDL against the only writer chokepoint (`store.py`) and the
readers (`db.py`, `research/api.py`, `search/engine.py`, `cli.py`):

| File | Lines read | Purpose |
|---|---|---|
| `vostlit_research/schema.sql` | 1–236 | DDL for all tables + FTS5 |
| `vostlit_research/store.py` | 1–254 | `upsert_document` — the only writer of `documents`/`document_versions`/`document_sections` |
| `vostlit_research/db.py` | 1–304 | Connection bootstrap, schema_version, FTS5 sync |
| `vostlit_research/io.py` | 1–196 | JSONL importer + `upsert_entity`/`upsert_name_variant`/`upsert_research_note` |
| `vostlit_research/models.py` | 1–123 | Pydantic boundary models |
| `vostlit_research/cli.py` | 1–676 | CLI commands incl. `works`, `note verify` |
| `vostlit_research/research/api.py` | 1–305 | `ResearchEngine` — `extract_mentions`, `find_mentions`, `compare_sources` |
| `vostlit_research/search/engine.py` | 1–120 (skim to 505) | `SearchResult.section_id`, FTS5 + exact + variant + fuzzy + toponym |

A reproduction sketch for the section-id stability question (#4) was written
to `/home/z/my-project/tmp_audit/verify_section_id_stability.py` (does NOT
modify any project code or schema; opens a fresh `:memory:` DB, applies the
existing `schema.sql`, replays `store.upsert_document` semantics). Its output
is quoted verbatim in §3.1.

---

## 2. Current model summary (table-by-table)

| Table | Role (one line) |
|---|---|
| `schema_version` | Single-row migration ledger; `db.py:25 SCHEMA_VERSION = 1`. |
| `documents` | One row per discovered URL (deduped by `canonical_url`); carries bibliographic metadata + `current_version_id` pointer. `AUTOINCREMENT`. |
| `document_versions` | Immutable snapshot of extracted_text + parser metadata; new row only when `content_hash` changes. `AUTOINCREMENT`. |
| `document_sections` | Ordered parts of a version (`section_type`, original `text`, `text_lower`, `page_number`, `anchor`). `AUTOINCREMENT`. |
| `entities` | Canonical person/place/settlement/society/state/ethnonym/organisation/event/work; `confidence` is categorical. |
| `name_variants` | Spellings of an entity with `evidence_section_id` → `document_sections(id)` `ON DELETE SET NULL`. |
| `mentions` | Entity/variant → document+section with exact `mention_text` and context; `section_id` `ON DELETE SET NULL`. |
| `research_notes` | Investigator claims with `status` enum and JSON `supporting_fragments`/`contradicting_fragments` (each `{section_id, quote, url}`). |
| `crawl_log` | Append-only URL audit (discovered/fetched/parsed/skipped/error). |
| `fts_sections` | FTS5 over normalised section heading+text. |
| `fts_documents` | FTS5 over normalised document metadata. |
| `fts_name_variants` | FTS5 over normalised name-variant forms. |
| `fts_entities` | FTS5 over entity canonical name + description. |

---

## 3. Confirmed defects

Severity scale: **CRITICAL** (silent data-loss / unrecoverable provenance),
**HIGH** (provenance gap that grows with corpus), **MEDIUM** (modeling gap
that forces lossy workarounds), **LOW** (cosmetic / future-proofing).

### 3.1  CRITICAL — Section ids are NOT stable on re-parse

**Symptom.** Re-importing a document — even when `extracted_text` is byte-
identical (`content_hash` matches → `action = 'unchanged'`) — causes every
`document_sections.id` for that document to be **deleted and re-issued with
new AUTOINCREMENT ids**. All references to the old section ids silently rot:

* `mentions.section_id` → `NULL` (FK is `ON DELETE SET NULL`, schema.sql:146)
* `name_variants.evidence_section_id` → `NULL` (FK is `ON DELETE SET NULL`, schema.sql:130)
* `research_notes.supporting_fragments[i].section_id` (stored in a JSON blob,
  schema.sql:165) → **silent orphan** (no FK on JSON columns — the row in
  `document_sections` is gone, but the JSON still names the dead id; see
  `cli.cmd_note_verify` at cli.py:423–425 which explicitly checks for this
  failure mode: `"reason": "section no longer exists"`).

**Code evidence.**

* `schema.sql:86` — `id INTEGER PRIMARY KEY AUTOINCREMENT` on
  `document_sections`. AUTOINCREMENT guarantees ids are never recycled but
  does NOT guarantee stability: a DELETE followed by INSERT always issues
  fresh ids.
* `store.py:161–177` — the section-write block:

  ```python
  if doc.sections and version_id is not None:
      # sections belong to this version; clear any prior sections for THIS version
      db.conn.execute(
          "DELETE FROM document_sections WHERE document_version_id = ?", (version_id,)
      )
      for i, s in enumerate(doc.sections):
          db.conn.execute("INSERT INTO document_sections ...")
  ```

  This block runs whenever `doc.sections` is non-empty AND `version_id is not
  None`. In the UNCHANGED path (`store.py:120–127`), `version_id` is set to
  the EXISTING `row["current_version_id"]` and then the section block still
  runs — so the existing version's sections are wiped and re-inserted with
  fresh ids even though the text did not change.

* `store.py:120–123` — the UNCHANGED path:
  ```python
  if prev["content_hash"] == content_hash and row is not None:
      # unchanged: keep current version
      version_id = row["current_version_id"]
  ```
  Comment says "keep current version" — the version row IS kept, but its
  child sections are clobbered 40 lines later.

**Reproduction sketch (verified).** See
`/home/z/my-project/tmp_audit/verify_section_id_stability.py`. Verbatim
output:

```
First insert: version_id=1, section_ids=[1, 2]
Citations recorded against section_id=1 (name_variant.evidence_section_id,
  mentions.section_id, research_note.supporting[0].section_id)

Re-parse #1 (UNCHANGED, content_hash matches):
  v1=1, v2=1, same_version_kept=True
  section_ids before: [1, 2]
  section_ids after:  [3, 4]
  section ids STABLE: False
  name_variants.evidence_section_id: now=None  -> DANGLING (set NULL by ON DELETE)
  mentions.section_id: now=None  -> DANGLING (set NULL by ON DELETE)
  research_note.supporting[0].section_id (JSON, no FK): 1  -> DANGLING (orphan, no FK protection)

Re-parse #2 (content CHANGED -> new version v2):
  section_ids after v3: [3, 5, 4, 6]
  OLD v1 sections surviving: 2 (expected 2 if old-version refs survive)
  NEW v2 sections: 2

--- CRITICAL: cite current-version section, re-parse UNCHANGED ---
  Citation recorded against current version section_id=1 (v1)
  Re-parse (UNCHANGED): version_id=1 (same=True), new section_ids=[3, 4]
  cited section_id=1 still exists: False
  -> If False: citation is silently orphaned. This is the CRITICAL defect.
```

**Key observations from the reproduction:**

1. Even on the UNCHANGED path, section ids change (1,2 → 3,4).
2. ON DELETE SET NULL fires on the two FK-backed columns
   (`mentions.section_id`, `name_variants.evidence_section_id`) → they
   silently become `NULL`. The provenance link is destroyed without warning.
3. The JSON-embedded section_id in `research_notes.supporting_fragments` is
   **not protected by any FK** — it survives as a dead integer pointing at a
   row that no longer exists. The CLI's own `note verify` (cli.py:423–425)
   knows to look for this, which is itself an admission of the defect.
4. The CHANGED-content path is actually safer than UNCHANGED: a NEW
   `document_versions` row is created, and OLD versions' sections survive
   (verified: v1 sections persist after a changed re-parse). The damage is
   limited to citations made against the CURRENT version, which are clobbered
   on the next re-parse.

**Severity: CRITICAL.** This breaks the central reproducibility promise of
the project — `references/citation-rules.md:19` defines the citation form
`[<document_id>#<section_id>] <Author>. <Title>. ...` and `citation-rules.md:63`
states: "A second agent running `context <section_id>` must see the same
text." After any re-crawl of the same URL, that contract is void.

**Minimal fix direction (for the migration plan, not applied here):**

* Compute a **stable, deterministic** identifier for each section independent
  of the AUTOINCREMENT id — e.g. `(document_id, version_number,
  sequence_number)` triple, or a `stable_key` column = `sha1(canonical_url ||
  ':' || version_number || ':' || sequence_number)`. Existing FKs would then
  point at the stable key.
* OR change `store.upsert_document` so the UNCHANGED path skips the
  section-rewrite block entirely (`if doc.sections and version_id is not
  None and action != 'unchanged':`). This requires no schema change but
  still leaves the CHANGED-path current-version-citation problem.
* OR add a `section_uuid TEXT UNIQUE` column to `document_sections`,
  populated by the parser as `uuid5(NAMESPACE, canonical_url + version +
  sequence_number + sha1(text)[:8])` and referenced by new FK columns on
  `mentions`/`name_variants`/`research_note_fragments`. Most invasive but
  most robust.

---

### 3.2  HIGH — `research_notes` fragment references have no referential integrity

**Symptom.** `supporting_fragments` and `contradicting_fragments` are stored
as JSON text blobs (schema.sql:165–166). The `section_id` integers inside
them are NOT FK-protected. A section can be deleted (see §3.1) and the note
will still claim it cites that section.

**Code evidence.**

* `schema.sql:165–166` — `supporting_fragments TEXT` / `contradicting_fragments TEXT` (JSON).
* `models.py:108–113` — `FragmentRef` is a Pydantic model with `section_id: int | None`, but the database cannot enforce its existence.
* `cli.py:418–428` — `cmd_note_verify` performs an explicit `SELECT id, document_id, text FROM document_sections WHERE id=?` for every cited fragment and reports `"reason": "section no longer exists"`. This is the runtime cost of the missing FK — every note must be re-verified on demand.
* `io.py:191` — `upsert_research_note` serialises `FragmentRef`s with `_json.dumps([f.model_dump() for f in n.supporting_fragments], ensure_ascii=False)`. No integrity check at write time.

**Severity: HIGH.** The defect compounds with §3.1: every re-parse silently
orphanates notes, and the only way to detect it is to run `note verify`
manually on every note.

---

### 3.3  HIGH — No schema-level model for work / edition relationships

**Symptom.** The `works` CLI groups documents into "works" purely by URL
path prefix. There is no schema-level way to say:

* "document B is a TRANSLATION of document A"
* "document C is PART_OF the collection indexed by document D"
* "document E is a CONTINUATION of document F"
* "document G is NOTES_FOR_TEXT of document H" (the `primtext<M>.phtml` pattern documented in `docs/SITE_AUDIT.md:56`)
* "document K is a SEPARATE_EDITION of document L"
* "document M is a REPUBLICATION of document N"

The current `_work_prefix` regex (cli.py:468–492) only handles two URL
shapes and returns `None` for everything else; relations that span URL
prefixes (a translation published under a different author's slug) cannot be
expressed at all.

**Code evidence.**

* `cli.py:436–465` — `cmd_works` groups by `_work_prefix(canonical_url)`.
* `cli.py:468–492` — `_work_prefix` returns `None` for any URL not matching `/Texts/rus[^/]*/[^/]+$` or `/Texts/Dokumenty/[^/]+/[^/]+/[^/]+/[^/]+$`. Frameset pages, notes pages, and translation pages that live in a sibling directory are silently dropped.
* `UPGRADE_BASELINE.md:103–104` — already flagged as a known defect: "Связи между произведениями основаны ТОЛЬКО на общем URL-префиксе (`_work_prefix`); нет отдельной таблицы связей с типом и доказательством."

**Severity: HIGH.** Without a relations table, the project cannot answer
"what are all the translations of the Derbend-name?" or "which documents
belong to the 'Дагестанские исторические сочинения' collection?" except by
free-text `collection` field matching (schema.sql:46), which is not
referentially enforced.

---

### 3.4  MEDIUM — No schema-level model for entity-to-entity relationships

**Symptom.** The `entities` table is a flat list. There is no way to record:

* "person P LIVED_IN place Q (attested in section S)"
* "person P was a MEMBER_OF society R"
* "person P AUTHORED work W"
* "settlement A is PART_OF region B"
* "state X SUCCEEDED state Y"
* "event E occurred AT place Q"

The only mechanism is free-text in `entities.notes` (schema.sql:113), which
is not searchable as a graph and carries no provenance.

**Code evidence.** `schema.sql:105–115` — `entities` has no relations table.
No `entity_relations` table anywhere in the schema.

**Severity: MEDIUM.** The historical-toponyms workflow
(`references/historical-toponyms.md`) implicitly needs these relations to
disambiguate toponyms ("Гумбет the village" vs "Гумбет the society"). Today
the disambiguation is done entirely in the agent's head and never recorded
in the DB, so the next agent has to redo it.

---

### 3.5  MEDIUM — Bibliography is a free-text blob; no structured per-source records

**Symptom.** `documents.bibliography` (schema.sql:48) is a single TEXT field
holding the whole `#dann` block. `ResearchEngine.get_document_bibliography`
(api.py:76–88) returns this blob plus any `section_type='bibliography'`
section rows — but neither is structured into individual bibliographic
entries (author, title, publisher, year, pages, URL).

The `lit.phtml` per-author bibliography pages (described in
`docs/SITE_AUDIT.md`) are not modeled at all.

**Code evidence.**

* `schema.sql:48` — `bibliography TEXT`.
* `api.py:76–88` — returns `{"bibliography": doc["bibliography"], "publication_title": ..., "bibliography_sections": [...]}`. No parsing into entries.
* No `bibliography_entries` table in the schema.

**Severity: MEDIUM.** Without structured entries, the system cannot answer
"which documents cite the same edition?" or "which sources were published by
Издательство АН СССР?" except by FTS over the blob, which loses field
semantics.

---

### 3.6  MEDIUM — No OCR-quality / suspected-OCR-error marker on sections

**Symptom.** The parser strips three colour-coded inline markers
(`[N]`/`{N}`/`<sup>N</sup>`, see `docs/SITE_AUDIT.md:65`) but has nowhere to
record that a given section's text contains suspected OCR errors. The
`name_variants.variant_type` enum includes `ocr_error` (schema.sql:128) — so
a single spelling can be flagged as an OCR artifact — but there is no
section-level flag to mark the whole passage as low-confidence.

**Code evidence.**

* `schema.sql:85–97` — `document_sections` has no `ocr_quality` or `suspected_ocr_error` column.
* `references/research-methodology.md` and `references/citation-rules.md` both instruct the agent to "mark OCR uncertainty" — but there is no DB column to mark it in.
* `SKILL.md:110` — "Mark OCR uncertainty." No storage target.

**Severity: MEDIUM.** OCR uncertainty is a first-class concern for a Cyrillic
corpus scanned from Soviet-era print. Without a column, the agent has to
re-derive OCR suspicion on every read.

---

### 3.7  MEDIUM — `mentions.section_id` and `name_variants.evidence_section_id` are nullable; provenance is not enforced

**Symptom.** A `mentions` row can exist with `section_id = NULL` — i.e., a
claim that an entity is mentioned somewhere in a document, with no
traceable evidence. Likewise a `name_variants` row with
`evidence_section_id = NULL` is, per `DATA_MODEL.md:62–64`, "a dictionary
entry, not a corpus attestation" — but the schema does not distinguish the
two cases structurally.

**Code evidence.**

* `schema.sql:130` — `evidence_section_id INTEGER REFERENCES document_sections(id) ON DELETE SET NULL` (nullable).
* `schema.sql:146` — `section_id INTEGER REFERENCES document_sections(id) ON DELETE SET NULL` (nullable).
* `DATA_MODEL.md:62–64` — explicitly acknowledges the gap: "A variant with no evidence section is a dictionary entry, not a corpus attestation." The schema makes this a soft convention, not an enforced rule.

**Severity: MEDIUM.** The ON DELETE SET NULL behavior (combined with §3.1)
means provenance is silently lost on re-parse. Even setting that aside, the
schema permits claims without evidence, which the project's own methodology
(`references/research-methodology.md`) forbids.

---

### 3.8  MEDIUM — Date/period model is free-text only; no structured period or range query

**Symptom.** Three different date-ish fields are all free TEXT:

* `documents.original_creation_date` (schema.sql:40) — free text, often a year or century
* `documents.publication_year` (schema.sql:41) — free text, may be a range or circa
* `entities.earliest_attested_date` / `latest_attested_date` (schema.sql:110–111) — free text

Date-range queries use `BETWEEN ... AND ...` on TEXT (api.py:134), which
only works correctly for ISO-8601 strings of identical length. "16th c." and
"1850" are not comparable as text.

There is no concept of a **historical period** (e.g. "the Safavid period in
Daghestan, 16th–18th c.") that an entity can be associated with.

**Code evidence.**

* `schema.sql:40–41, 110–111` — all four date columns are TEXT.
* `api.py:129–137` — `search_by_date` uses `COALESCE(publication_year, original_creation_date, '') BETWEEN COALESCE(?, '') AND COALESCE(?, 'zzz')`. The `'zzz'` upper bound is a workaround for the type-system gap.
* `search/engine.py:92–97` — same `COALESCE(...) >= ?` pattern.

**Severity: MEDIUM.** "Гумбет existed 16th–19th c." cannot be modeled as a
queryable range. The agent can record it as free text in `entities.notes`,
but no other agent can query against it.

---

### 3.9  LOW — `document_sections.id` AUTOINCREMENT vs. stable-identity tension

**Symptom.** The schema-level comment (schema.sql:4–6) says AUTOINCREMENT is
used "only where reuse must be avoided (documents, document_versions) so a
referenced id can never be recycled after a delete." But
`document_sections` ALSO uses AUTOINCREMENT (schema.sql:86), even though
sections are deleted and re-inserted on every parse. The intent of the
comment is violated by the sections table.

**Code evidence.** `schema.sql:4–6` (comment) vs. `schema.sql:86` (sections
column). The comment's stated rule is "AUTOINCREMENT only where reuse must
be avoided" — but for sections, the issue is not reuse, it is stability
across re-parse, which AUTOINCREMENT does not provide.

**Severity: LOW.** This is a documentation-vs-implementation drift, not a
functional bug. It is the root cause that makes §3.1 possible.

---

### 3.10  LOW — `documents.collection` is free text; not a FK to a collections table

**Symptom.** Collections like "Дагестанские исторические сочинения"
(`docs/SITE_AUDIT.md:52`) are recorded as a free-text string. Typos and
variant spellings produce phantom collections.

**Code evidence.** `schema.sql:46` — `collection TEXT`.

**Severity: LOW.** A `collections` table with FK would prevent drift, but
the cost is low until the corpus grows.

---

## 4. Proposed additions (conservative, justified)

Each proposal lists table/column, purpose, migration path, and
backward-compat note. Proposals are ordered by severity-addressed.

### 4.1  `document_sections.stable_key TEXT UNIQUE` (or migrate FKs to a composite)

* **Purpose:** Make every section reference survive a re-parse. The
  `stable_key` is a deterministic hash of `(canonical_url, version_number,
  sequence_number)` and is computed at INSERT time. FK columns on
  `mentions`, `name_variants`, and the new `research_note_fragments` table
  point at `stable_key` instead of (or in addition to) the AUTOINCREMENT id.
* **Migration path:** v2 → `ALTER TABLE document_sections ADD COLUMN stable_key TEXT`;
  backfill `stable_key = sha1(canonical_url || ':' || version_number || ':' || sequence_number)`
  via a JOIN with `documents` + `document_versions`; then `CREATE UNIQUE INDEX idx_sections_stablekey ON document_sections(stable_key)`.
  Code change in `store.upsert_document` to compute and pass `stable_key`
  at INSERT time, and to skip the DELETE+re-INSERT in the UNCHANGED path.
* **Backward-compat note:** Existing `section_id` INTEGER FKs remain valid
  (the AUTOINCREMENT id still exists); the new `stable_key` is ADDITIVE.
  Old code that reads by `section_id` keeps working. New code can opt into
  `stable_key` for citation.
* **Justification:** This is the only proposal that addresses a CRITICAL
  defect. It is justified.

### 4.2  `research_note_fragments` table (replaces JSON blobs in `research_notes`)

* **Purpose:** Move `supporting_fragments` / `contradicting_fragments` out
  of JSON and into a real table with FK to `document_sections(id)` (or
  `stable_key`). Each row = one fragment: `(note_id, role, section_id,
  document_id, quote, url)`. ON DELETE behavior: `SET NULL` on
  `section_id` (signal that the citation is dangling) but `document_id`
  stays (the document is retained even if the section moved). Add a
  `verified_at` timestamp updated by `note verify`.
* **Migration path:** v3 → `CREATE TABLE research_note_fragments (...)`;
  backfill by parsing the existing JSON columns; keep the JSON columns for
  one release as a fallback, then DROP them in v4.
* **Backward-compat note:** `note show` (cli.py:386–401) currently
  deserialises the JSON; it would be re-pointed at the new table. No
  user-facing CLI change.
* **Justification:** Addresses §3.2 (HIGH). Pairs with §4.1.

### 4.3  `document_relations` table

* **Purpose:** Schema-level model for work/edition relationships. Columns:
  `(id, source_doc_id, target_doc_id, relation_type, evidence_section_id,
  created_at, notes)`. `relation_type` ∈ {part_of, continuation,
  notes_for_text, separate_edition, republication, translation_of,
  mentioned_in, indexed_by}. `evidence_section_id` is the section where the
  relation is asserted (e.g. a preface saying "this is a translation of X").
* **Migration path:** v4 → `CREATE TABLE document_relations (...)`. The
  `works` CLI keeps its URL-prefix grouping as a default heuristic but
  augments with `SELECT * FROM document_relations WHERE relation_type IN
  ('part_of','translation_of','separate_edition')`.
* **Backward-compat note:** Pure addition. No existing data affected.
* **Justification:** Addresses §3.3 (HIGH). Already flagged in
  `UPGRADE_BASELINE.md:103–104`.

### 4.4  `entity_relations` table

* **Purpose:** Schema-level model for entity-to-entity claims. Columns:
  `(id, subject_entity_id, object_entity_id, relation_type,
  evidence_section_id, date_range, confidence, verification_status,
  created_at)`. `relation_type` ∈ {lived_in, member_of, authored, part_of,
  succeeded, occurred_at, ruled, born_in, died_in, ...}.
* **Migration path:** v5 → `CREATE TABLE entity_relations (...)`. No
  backfill (free-text `entities.notes` cannot be reliably parsed into
  structured triples without manual review).
* **Backward-compat note:** Pure addition.
* **Justification:** Addresses §3.4 (MEDIUM). Conservative: the relation
  type vocabulary is left open (TEXT, not an enum) so the historical-
  knowledge model can grow without further migrations.

### 4.5  `document_sections.ocr_quality` column

* **Purpose:** A nullable TEXT or enum column on `document_sections` to flag
  OCR suspicion. Values: `NULL` (not assessed), `clean`, `suspected_errors`,
  `severe_errors`. Optionally a `ocr_notes` TEXT for specifics.
* **Migration path:** v6 → `ALTER TABLE document_sections ADD COLUMN ocr_quality TEXT`.
* **Backward-compat note:** Nullable addition. Default NULL = "not assessed".
* **Justification:** Addresses §3.6 (MEDIUM). Low cost; the parser already
  has heuristics (long runs of consonants, malformed Cyrillic) that could
  populate it.

### 4.6  `historical_periods` table + `entity_periods` join

* **Purpose:** Structured model for periods like "Safavid Daghestan, 1501–1736".
  Columns: `(id, name, region, start_year_int, end_year_int, calendar,
  notes)`. Join table `entity_periods(entity_id, period_id, role,
  evidence_section_id)`.
* **Migration path:** v7 → `CREATE TABLE historical_periods (...)` +
  `CREATE TABLE entity_periods (...)`. Add `earliest_attested_year_int` /
  `latest_attested_year_int` INTEGER columns to `entities` as a
  denormalised query aid.
* **Backward-compat note:** Pure addition. The existing TEXT date columns
  remain as the human-readable form.
* **Justification:** Addresses §3.8 (MEDIUM). The integer columns make the
  `search_by_date` workaround at `api.py:134` unnecessary.

### 4.7  `bibliography_entries` table

* **Purpose:** Structured per-source bibliography records. Columns: `(id,
  document_id, entry_type, authors_json, title, publisher, place, year,
  pages, url, source_section_id)`. One row per cited edition / source in
  the `#dann` block.
* **Migration path:** v8 → `CREATE TABLE bibliography_entries (...)`. No
  backfill (parsing the free-text `bibliography` blob reliably is a
  research task, not a migration). The `bibliography` blob is retained as
  the original; the new table is the structured derivative.
* **Backward-compat note:** Pure addition.
* **Justification:** Addresses §3.5 (MEDIUM). Defer until the parser can
  reliably split the `#dann` block into entries; this is a v2-feature,
  not a v1-fix.

### 4.8  NOT proposed (deliberately conservative)

* **Full-text search on `research_notes.claim` / `argumentation`.** Not
  justified today: the notes table is small (manual curation), and a
  `LIKE` query is adequate. Adding an FTS5 index would add sync cost
  without measurable benefit.
* **Replacing `entities.confidence` categorical with a numeric score.** The
  project explicitly rejects fake percentages (`DATA_MODEL.md:56`). Sound
  design — keep.
* **Enum constraints on `relation_type` / `variant_type` / `section_type`.**
  SQLite CHECK constraints would prevent future vocabulary growth. The
  current TEXT-with-convention approach is appropriate for an evolving
  historical model. Keep.
* **Triggers to auto-sync FTS5.** The current explicit-`reindex_*` design
  (db.py:97–272) is correct: normalisation is Python-side, triggers would
  duplicate logic. Keep.

---

## 5. What NOT to change (existing sound decisions)

These design decisions are correct and should be preserved through any
migration:

1. **`documents` + `document_versions` + `document_sections` triple.**
   Immutable-version-with-current-pointer is the right pattern for a
   reproducible corpus. (schema.sql:31–100)
2. **AUTOINCREMENT on `documents` and `document_versions`.** Correctly
   prevents id recycling after deletes. (schema.sql:32, 68)
3. **Original-text + normalised-derivative split.** `text` keeps the
   windows-1251-decoded original; `text_lower` is a Cyrillic-aware lower
   copy; FTS5 indexes hold `normalise_search` output. Three layers, each
   with a distinct purpose. (schema.sql:7–16; db.py:97–272)
4. **Explicit FTS5 reindex, not triggers.** Normalisation logic lives in
   `textnorm.normalise_search`; triggers would duplicate it in SQL.
   (db.py:8–11 comment)
5. **Categorical confidence (`verified|probable|possible|unestablished`).**
   No fake percentages. (schema.sql:112, 170)
6. **`research_notes.status` enum + `change_history` JSON.** A hypothesis
   cannot silently become a `source_fact`. (schema.sql:164, 171)
7. **`crawl_log` append-only.** Resume + audit both depend on it.
   (schema.sql:178–190)
8. **`ON DELETE CASCADE` for `document_versions` → `document_versions`**
   and **`ON DELETE SET NULL` for evidence FKs** (schema.sql:87, 88, 130,
   146). The cascade is correct (deleting a document takes its versions
   and sections); the set-null is the right *intent* for evidence FKs
   (preserve the claim, lose the link) — the defect in §3.1 is that the
   link is lost too eagerly, not that set-null is the wrong policy.
9. **`PRAGMA foreign_keys = ON` set both in schema.sql:18 and on every
   connection in db.py:42.** Defense in depth — keep.
10. **`schema_version` migration ledger.** Simple, correct, already in
    place. (schema.sql:23–26; db.py:25, 57–68)

---

## 6. Migration plan (ordered, backward-compatible, with schema_version bumps)

Each migration is a single forward step. The `schema_version` table is
append-only. Migrations are applied by `db._ensure_schema` (db.py:57–68),
which today only runs the DDL `IF NOT EXISTS` blocks; a real migration
runner needs to be added (out of scope for this audit — flagged for the
main agent).

### Migration to v2 — fix section-id stability (CRITICAL)

**Files touched:** `schema.sql`, `store.py`, `db.py`.

1. `ALTER TABLE document_sections ADD COLUMN stable_key TEXT;`
2. Backfill: `UPDATE document_sections SET stable_key = ...` via a Python
   script that joins `documents` + `document_versions` to compute
   `sha1(canonical_url || ':' || version_number || ':' || sequence_number)`.
3. `CREATE UNIQUE INDEX IF NOT EXISTS idx_sections_stable_key ON document_sections(stable_key);`
4. In `store.upsert_document`:
   * Compute `stable_key` for each incoming section.
   * On the UNCHANGED path (`content_hash` matches): **skip the DELETE +
     INSERT block entirely** (the existing sections already match by
     `stable_key`).
   * On the CHANGED path: INSERT new sections with their `stable_key`;
     old version's sections are untouched (already the case).
5. Add `stable_key` columns (nullable, with FK) to `mentions` and
   `name_variants`, populated alongside the existing `section_id` columns.
   `note verify` reads `stable_key` first, falls back to `section_id`.

**Schema-version bump:** 1 → 2.
**Risk:** Low. Existing `section_id` FKs remain valid. New code writes
both; old code reads `section_id` and continues to work.

### Migration to v3 — research_note_fragments (HIGH)

1. `CREATE TABLE research_note_fragments (id INTEGER PRIMARY KEY AUTOINCREMENT,
   note_id INTEGER NOT NULL REFERENCES research_notes(id) ON DELETE CASCADE,
   role TEXT NOT NULL, section_id INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
   stable_key TEXT REFERENCES document_sections(stable_key) ON DELETE SET NULL,
   document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
   quote TEXT, url TEXT, verified_at TEXT);`
2. Backfill from `research_notes.supporting_fragments` /
   `contradicting_fragments` JSON.
3. `cli.cmd_note_show` and `cli.cmd_note_verify` read from the new table.
4. (v4 later) `ALTER TABLE research_notes DROP COLUMN supporting_fragments;`
   `ALTER TABLE research_notes DROP COLUMN contradicting_fragments;`

**Schema-version bump:** 2 → 3.
**Risk:** Low. JSON columns retained through v3 for fallback.

### Migration to v4 — document_relations (HIGH)

1. `CREATE TABLE document_relations (id INTEGER PRIMARY KEY AUTOINCREMENT,
   source_doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
   target_doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
   relation_type TEXT NOT NULL, evidence_section_id INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
   evidence_stable_key TEXT, date_range TEXT, notes TEXT, created_at TEXT NOT NULL,
   CHECK (source_doc_id <> target_doc_id));`
2. `CREATE INDEX idx_docrel_source ON document_relations(source_doc_id);`
3. `CREATE INDEX idx_docrel_target ON document_relations(target_doc_id);`
4. `CREATE INDEX idx_docrel_type ON document_relations(relation_type);`

**Schema-version bump:** 3 → 4.
**Risk:** Pure addition. No backfill (relations are asserted, not
inferred). The `works` CLI keeps its URL-prefix heuristic as a default.

### Migration to v5 — entity_relations (MEDIUM)

1. `CREATE TABLE entity_relations (id INTEGER PRIMARY KEY AUTOINCREMENT,
   subject_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
   object_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
   relation_type TEXT NOT NULL, evidence_section_id INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
   evidence_stable_key TEXT, date_range TEXT, confidence TEXT,
   verification_status TEXT NOT NULL DEFAULT 'unverified', created_at TEXT NOT NULL,
   CHECK (subject_entity_id <> object_entity_id));`
2. Indexes on subject, object, type.

**Schema-version bump:** 4 → 5.
**Risk:** Pure addition.

### Migration to v6 — document_sections.ocr_quality (MEDIUM)

1. `ALTER TABLE document_sections ADD COLUMN ocr_quality TEXT;`
2. `ALTER TABLE document_sections ADD COLUMN ocr_notes TEXT;`
3. Convention: `ocr_quality ∈ {NULL, 'clean', 'suspected_errors', 'severe_errors'}`.
   No CHECK constraint (vocabulary may grow).

**Schema-version bump:** 5 → 6.
**Risk:** Low. Nullable addition.

### Migration to v7 — historical_periods + entity_periods + integer year columns (MEDIUM)

1. `CREATE TABLE historical_periods (id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT NOT NULL, region TEXT, start_year_int INTEGER, end_year_int INTEGER,
   calendar TEXT, notes TEXT);`
2. `CREATE TABLE entity_periods (id INTEGER PRIMARY KEY AUTOINCREMENT,
   entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
   period_id INTEGER NOT NULL REFERENCES historical_periods(id) ON DELETE CASCADE,
   role TEXT, evidence_section_id INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
   evidence_stable_key TEXT, UNIQUE (entity_id, period_id, role));`
3. `ALTER TABLE entities ADD COLUMN earliest_attested_year_int INTEGER;`
4. `ALTER TABLE entities ADD COLUMN latest_attested_year_int INTEGER;`
5. Backfill integer columns from the TEXT columns where the text is a
   bare 3–4 digit year (best-effort; NULL otherwise).

**Schema-version bump:** 6 → 7.
**Risk:** Low. `api.search_by_date` can be updated to use the new integer
columns when present, falling back to the TEXT workaround otherwise.

### Migration to v8 — bibliography_entries (MEDIUM, deferred)

1. `CREATE TABLE bibliography_entries (id INTEGER PRIMARY KEY AUTOINCREMENT,
   document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
   entry_type TEXT, authors_json TEXT, title TEXT, publisher TEXT, place TEXT,
   year TEXT, pages TEXT, url TEXT, source_section_id INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
   source_stable_key TEXT);`
2. Index on `document_id`, on `year`, on `publisher`.

**Schema-version bump:** 7 → 8.
**Risk:** Pure addition. Defer until the `#dann` parser can populate it
reliably.

---

### Ordering summary

| Step | schema_version | Addresses | Severity fixed |
|---|---|---|---|
| v2 | 1 → 2 | §3.1 (section-id stability) + §3.9 | CRITICAL |
| v3 | 2 → 3 | §3.2 (research_note fragment FKs) | HIGH |
| v4 | 3 → 4 | §3.3 (document_relations) | HIGH |
| v5 | 4 → 5 | §3.4 (entity_relations) | MEDIUM |
| v6 | 5 → 6 | §3.6 (ocr_quality) | MEDIUM |
| v7 | 6 → 7 | §3.8 (historical_periods + int years) | MEDIUM |
| v8 | 7 → 8 | §3.5 (bibliography_entries) | MEDIUM |
| (skipped) | — | §3.7 (nullable evidence) | MEDIUM — addressed structurally by v2+v3 |
| (skipped) | — | §3.10 (collections FK) | LOW — defer |

**Total: 7 migrations, all backward-compatible, all additive except the
eventual DROP of the JSON fragment columns in v4.**

---

## Appendix A — Files NOT modified by this audit

Per the task constraints, this audit did NOT modify any source code or
schema. The only files written are:

* `/home/z/my-project/vostlit-research/docs/SCHEMA_AUDIT.md` (this file)
* `/home/z/my-project/tmp_audit/verify_section_id_stability.py` (reproduction sketch, outside the project tree)
* `/home/z/my-project/worklog.md` (append-only, per the shared-worklog protocol)

No changes to `schema.sql`, `store.py`, `db.py`, `io.py`, `cli.py`,
`models.py`, `api.py`, `engine.py`, or any test file.
