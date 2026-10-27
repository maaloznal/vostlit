# Research Methodology

This document defines the *method* the agent must follow when using the
vostlit-research corpus. It is the operational counterpart of the rules in
`SKILL.md`.

## 1. The central principle

> Every historical conclusion must keep a verifiable link to a specific
> fragment of a specific source.

A "source" is a document row in the local DB (with a `canonical_url` back to
vostlit.info). A "fragment" is a `document_sections` row. A conclusion that
cannot name its fragments is not a result — it is a guess.

## 2. Decompose before searching

Before any search, write down (internally):

- **Entities**: persons, peoples, places, societies, states, works.
- **Dates**: the date the *event* happened vs. the date the *source* was
  written vs. the date of the *edition* you are reading. These are three
  different things.
- **Geography**: the region and the neighbouring societies (e.g. Гумбет
  borders Салатавия, Андийское общество, Авария).
- **The claim**: stated as a single testable sentence.

## 3. Variant expansion

For every toponym, generate candidate spellings:

1. The form given by the user.
2. Pre-reform Russian (ѣ→е, і→и, ѳ→ф, ѵ→и; final ъ).
3. ё↔е variants.
4. Common transliterations (German/French/English: e.g. dj/gj, ch/ч, y/ы/й).
5. The toponym with generic terms added AND removed:
   `гора Джалдари-меер` ↔ `Джалдари-меер` ↔ `Джалдари` (the core, after
   stripping гора/хребет/перевал/урочище/меер/…).

Run `search-variants` and `search-fuzzy` for each. **Fuzzy hits are
candidates, never identities.**

## 4. Search ladder

Run, in order, and record what each returned:

1. `search-exact "<core toponym>"` — exact phrase in original text.
2. `search "<core>"` — FTS5 ranked (ё/pre-reform-insensitive).
3. `search-exact "<full form with generic>"` — e.g. `гора Джалдари`.
4. `search-variants "<each variant>"`.
5. `search-fuzzy "<core>"` — only to surface candidates you then verify.
6. `by-region <region> "<core>"` — restrict to the right geography.

## 5. Read in context

For every hit, call `context <section_id> --before 2 --after 2`. A fragment
without context is uninterpretable: the same word can name different places,
and a clause can be negated two sentences later.

## 6. Source criticism (per hit)

For each source you cite, confirm:

- **Author** and **date of writing** (≠ publication date of the edition).
- **Provenance**: is it a primary source (witness) or a later compilation?
- **Edition** being reproduced (`bibliography <id>`).
- **Language** and whether you are reading a translation.
- **Region/period** fit: does this source plausibly know about the place?

## 7. Triangulation

- Look for **independent** corroboration. Two excerpts that both cite, or both
  translate, the SAME earlier chronicle are ONE witness, not two.
- Look for **contradictions** explicitly. Use
  `compare "<claim>" <id1> <id2> ...` to gather both sides.
- Record which sources agree, which disagree, and which are silent.

## 8. Separate testimony from interpretation

- **Source fact**: the document literally says X (quote it).
- **Interpretation**: you infer X from what the document says (argue it).
- **Hypothesis**: you suspect X but the sources do not state it (flag it).
- **Refuted**: sources contradict X (show the contradiction).

Never let an interpretation drift into a "source fact" silently.

## 9. When the corpus is insufficient

If searches return nothing:

- SAY the corpus has no hit for this query. Do not infer that the event did
  not happen.
- Propose the concrete next step: `crawl --region caucasus --limit N`, or
  search a specific variant, or import a named JSONL.

## 10. Reproducibility

A second agent running the same searches on the same DB must be able to
reproduce your cited fragments. So always cite `document_id` + `section_id` +
`canonical_url`, and prefer quoting the exact `text` of the section.
