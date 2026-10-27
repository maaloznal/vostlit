-- vostlit_research — SQLite schema (version 1)
--
-- Design notes:
--   * INTEGER PRIMARY KEY ids everywhere; AUTOINCREMENT only where reuse must
--     be avoided (documents, document_versions) so a referenced id can never
--     be recycled after a delete.
--   * All free-text columns keep the ORIGINAL spelling (windows-1251 decoded
--     into proper Unicode). Normalisation is a separate, derived view — it is
--     never allowed to overwrite the original.
--   * FTS5 tables are non-contentless with UNINDEXED id columns, so we can use
--     ordinary DELETE/INSERT to keep them in sync. The indexed columns hold
--     NORMALISED text (see vostlit_research.textnorm.normalise_search) so that
--     ё=е, pre-reform ѣ/і/ѳ fold to modern forms, and search is case-folded.
--   * document_sections also stores text_lower (Cyrillic-aware lower-cased
--     original) for case-insensitive EXACT phrase matching that still
--     distinguishes ё from е (SQLite's LOWER()/NOCASE only handle ASCII).

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------
-- Schema version (single source of truth for migrations)
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT    NOT NULL
);

-- ----------------------------------------------------------------------
-- documents: one row per discovered source page (stable by canonical_url)
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_url            TEXT    NOT NULL UNIQUE,  -- normalised URL (no fragment; id query kept)
    stable_id                TEXT,                     -- the `id` query param for .phtml, or the path for .htm
    page_type                TEXT,                     -- home|alpha_index|documents_hub|region_catalog|...
    title                    TEXT,
    author                   TEXT,
    translator               TEXT,
    editor                   TEXT,
    original_creation_date   TEXT,                     -- date the SOURCE describes (NOT the publication date)
    publication_year         TEXT,                     -- kept as TEXT: years can be ranges or circa
    publication_title        TEXT,                     -- "Текст воспроизведен по изданию: ..." line
    source_type              TEXT,                     -- chronicle|letter|report|map|...
    language                 TEXT,
    region                   TEXT,                     -- e.g. Кавказ, Дагестан, Салатавия, Гумбет
    collection               TEXT,                     -- e.g. "Дагестанские исторические сочинения"
    description              TEXT,
    bibliography             TEXT,                     -- full bibliography block (text)
    source_metadata_json     TEXT,                     -- arbitrary verified metadata (JSON)
    first_seen_at            TEXT    NOT NULL,
    last_checked_at          TEXT,
    retrieved_at             TEXT,                     -- last successful text retrieval
    content_hash             TEXT,                     -- sha256 of extracted_text (current version)
    current_version_id       INTEGER,                  -- -> document_versions.id
    status                   TEXT    NOT NULL DEFAULT 'discovered',
    error_message            TEXT,
    FOREIGN KEY (current_version_id) REFERENCES document_versions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_status   ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_type     ON documents(page_type);
CREATE INDEX IF NOT EXISTS idx_documents_region   ON documents(region);
CREATE INDEX IF NOT EXISTS idx_documents_stable   ON documents(stable_id);

-- ----------------------------------------------------------------------
-- document_versions: immutable snapshots of extracted content
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_versions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id          INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number       INTEGER NOT NULL,
    extracted_text       TEXT,                         -- full plain text of the body (original spelling)
    original_html_path   TEXT,                         -- relative path inside the archive, or NULL
    extraction_method    TEXT,                         -- parser branch used: phtml|htm|...
    extracted_at         TEXT    NOT NULL,
    content_hash         TEXT,                         -- sha256(extracted_text)
    parser_version       TEXT    NOT NULL,
    extraction_warnings  TEXT,                         -- JSON list of warnings (e.g. "no #dann found")
    UNIQUE (document_id, version_number)
);
CREATE INDEX IF NOT EXISTS idx_versions_doc ON document_versions(document_id);

-- ----------------------------------------------------------------------
-- document_sections: structured parts of a version
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_sections (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    document_version_id  INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    document_id          INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_type         TEXT NOT NULL,                -- body|heading|footnote|note|bibliography|caption|page_break|chapter_marker
    heading              TEXT,
    text                 TEXT,                         -- ORIGINAL spelling
    text_lower           TEXT,                         -- Cyrillic-aware lowercased original (for exact CI match)
    sequence_number      INTEGER NOT NULL,
    page_number          TEXT,                         -- print-edition page when known (e.g. "89")
    anchor               TEXT,                         -- in-page anchor when known
    source_url           TEXT                          -- URL the section came from (may differ from doc url for notes pages)
);
CREATE INDEX IF NOT EXISTS idx_sections_version ON document_sections(document_version_id);
CREATE INDEX IF NOT EXISTS idx_sections_doc     ON document_sections(document_id);
CREATE INDEX IF NOT EXISTS idx_sections_type    ON document_sections(section_type);

-- ----------------------------------------------------------------------
-- entities: canonical historical entities (person, place, people, event...)
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name        TEXT NOT NULL,
    entity_type           TEXT NOT NULL,               -- person|place|settlement|society|state|ethnonym|organisation|event|work
    description           TEXT,
    earliest_attested_date TEXT,
    latest_attested_date  TEXT,
    confidence            TEXT,                        -- verified|probable|possible  (no fake percentages)
    notes                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

-- ----------------------------------------------------------------------
-- name_variants: spellings of an entity, each with provenance
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS name_variants (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id              INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    original_form          TEXT NOT NULL,              -- as printed in the source
    normalized_form        TEXT NOT NULL,              -- normalised for search (see textnorm)
    language               TEXT,
    script                 TEXT,                       -- Cyrillic|Latin|Arabic|...
    transliteration_system TEXT,
    variant_type           TEXT,                       -- historical|modern|ocr_error|transliteration|alias
    date_range             TEXT,
    evidence_section_id    INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    confidence             TEXT,                       -- verified|probable|candidate
    verification_status    TEXT NOT NULL DEFAULT 'unverified'  -- unverified|candidate|confirmed|rejected
);
CREATE INDEX IF NOT EXISTS idx_variants_entity   ON name_variants(entity_id);
CREATE INDEX IF NOT EXISTS idx_variants_norm     ON name_variants(normalized_form);
CREATE INDEX IF NOT EXISTS idx_variants_original ON name_variants(original_form);

-- ----------------------------------------------------------------------
-- mentions: an entity (or bare name) appears in a document section
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mentions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id         INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    name_variant_id   INTEGER REFERENCES name_variants(id) ON DELETE SET NULL,
    document_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id        INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    mention_text      TEXT NOT NULL,                   -- the exact span as printed
    context_before    TEXT,
    context_after     TEXT,
    mention_type      TEXT,                            -- explicit|inferred|candidate
    extraction_method TEXT,                            -- manual|regex|heuristic
    verification_status TEXT NOT NULL DEFAULT 'unverified'
);
CREATE INDEX IF NOT EXISTS idx_mentions_entity  ON mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_doc     ON mentions(document_id);
CREATE INDEX IF NOT EXISTS idx_mentions_section ON mentions(section_id);

-- ----------------------------------------------------------------------
-- research_notes: hypotheses/findings, kept strictly separate from sources
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_notes (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    claim                    TEXT NOT NULL,
    status                   TEXT NOT NULL,            -- source_fact|interpretation|hypothesis|refuted
    supporting_fragments     TEXT,                     -- JSON list of {section_id, quote, url}
    contradicting_fragments  TEXT,                     -- JSON list of {section_id, quote, url}
    argumentation            TEXT,
    author_or_mechanism      TEXT,
    created_at               TEXT NOT NULL,
    confidence               TEXT,                     -- verified|probable|possible|unestablished
    change_history           TEXT                      -- JSON list of {at, by, change}
);
CREATE INDEX IF NOT EXISTS idx_notes_status ON research_notes(status);

-- ----------------------------------------------------------------------
-- crawl_log: every URL the collector has touched (for resume & audit)
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    fetched_at    TEXT,
    http_status   INTEGER,
    content_hash  TEXT,
    bytes         INTEGER,
    action        TEXT,                                -- discovered|fetched|parsed|skipped|error
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS idx_crawllog_url     ON crawl_log(canonical_url);
CREATE INDEX IF NOT EXISTS idx_crawllog_action  ON crawl_log(action);

-- ----------------------------------------------------------------------
-- FTS5: full-text indexes over NORMALISED text (see textnorm.normalise_search)
-- ----------------------------------------------------------------------

-- Body & heading search across sections.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_sections USING fts5(
    heading_norm,
    text_norm,
    document_id UNINDEXED,
    section_id UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2 categories 'L* N* Co'"
);

-- Metadata search across documents.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents USING fts5(
    title_norm,
    author_norm,
    translator_norm,
    editor_norm,
    publication_title,
    region_norm,
    collection_norm,
    description_norm,
    bibliography_norm,
    document_id UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2 categories 'L* N* Co'"
);

-- Name-variant search (original + normalised forms).
CREATE VIRTUAL TABLE IF NOT EXISTS fts_name_variants USING fts5(
    original_norm,
    normalized_form,
    entity_id UNINDEXED,
    variant_id UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2 categories 'L* N* Co'"
);

-- Entity canonical names & descriptions.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_entities USING fts5(
    canonical_name,
    description,
    entity_id UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2 categories 'L* N* Co'"
);
