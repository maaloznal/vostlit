# Source Evaluation

How to judge a source once you have found it. Adapted from classical historical
criticism, applied to the vostlit.info corpus.

## 1. The three dates

Every document row has up to three date fields — do not conflate them:

| Field | Meaning | Example |
|-------|---------|---------|
| `original_creation_date` | When the **source text** was written / the event occurred | 1792 (the Dagestan-poddanstvo document) |
| `publication_year` | When the **edition being reproduced** was published | 2003 (Исторический архив, № 4) |
| `first_seen_at` / `retrieved_at` | When **we** imported/fetched it | 2025-10-27 |

A claim about "what happened in 1792" relies on `original_creation_date`; a
citation in a bibliography relies on `publication_year`.

## 2. Source type ladder (trust gradient)

From strongest to weakest for a claim about event X:

1. **Contemporary witness** — written at the time of X by someone who could
   have seen it.
2. **Near-contemporary narrative** — written within a generation, drawing on
   witnesses.
3. **Later chronicle** — written centuries later; may preserve older material
   but also invention.
4. **Documentary/act** — an administrative text (treaty, oath, report). High
   for what it records, low for motives.
5. **Scholarly edition's notes** — the editor's commentary (marked
   `section_type='note'`); this is secondary literature, not a primary source.

The parser tags sections `body`, `note`, `bibliography`, `heading`,
`page_break`, `chapter_marker`, `caption`. **Cite `body` for testimony; cite
`note` only as the editor's opinion.**

## 3. Edition vs. original

The corpus reproduces a *specific edition* (`publication_title`). When you
quote, you are quoting that edition's text, which may be:

- a translation (check `translator`),
- a critical reconstruction (the editor may have emended the text),
- an OCR of a printed book (flag OCR uncertainty).

If you need the original-language text, check whether the work has a
`frame*.htm`/`text*.phtml` part labelled "Текст" vs. "Перевод".

## 4. Provenance flags

Be extra cautious when:

- the document is in `/Texts/Dokumenty/Kavkaz/.../` (often smaller archival
  pieces — check the `archive_signature` in `source_metadata`),
- the title is generic ("Дагестанские владения…") — verify the specific place,
- the `extraction_warnings` list is non-empty (parser had trouble).

## 5. Two excerpts = one witness?

Before counting corroboration, check whether two excerpts:

- come from the same `document_id` (trivially one witness),
- come from documents that explicitly cite each other (check `bibliography`),
- belong to a collection (e.g. "Дагестанские исторические сочинения") that
  shares a common source chronicle.

`compare_sources` helps gather the fragments, but the independence judgment is
yours.

## 6. OCR and orthography

- Pre-reform letters (ѣ і ѳ ѵ) are preserved as-is in `text`. They are not
  errors.
- Suspected OCR errors appear as odd character sequences; if a name looks
  garbled, try `search-fuzzy` and check multiple attestations before
  accepting the reading.
- Never present OCR text as a verified transcription. Mark it "OCR, unverified".
