# Research Workflow

The end-to-end method an agent (or human) follows with this system. This is
the prose version of `references/research-methodology.md`, focused on *what
to type*.

## Phase 0 — Health check

```bash
python3 -m vostlit_research doctor
python3 -m vostlit_research stats
```

If `documents == 0`, import or crawl first (Phases 1–2). Do not research
against an empty corpus.

## Phase 1 — Seed / import

- From the verified fixtures (offline, instant):
  `python3 scripts/seed_corpus.py`
- From a JSONL export: `python3 -m vostlit_research import-jsonl corpus.jsonl`

## Phase 2 — Extend (optional, hits the live site)

```bash
python3 -m vostlit_research crawl --region caucasus --limit 25
# or, to only build the inventory without fetching text:
python3 -m vostlit_research crawl --region caucasus --discover-only
```

The client sleeps `request_delay` (default 3 s) between requests and caps at
`max_pages_per_run` (25). Re-running skips already-parsed docs (`status=
unchanged`), so you can resume.

## Phase 3 — Research a question

1. **Decompose** the question into entities/dates/geography/claim.
2. **Expand variants** for each toponym (pre-reform, transliterations, with
   and without generic terms). See `references/historical-toponyms.md`.
3. **Search ladder** (record what each returned):
   ```bash
   python3 -m vostlit_research search-exact "<core>"
   python3 -m vostlit_research search "<core>"
   python3 -m vostlit_research search-variants "<variant>"
   python3 -m vostlit_research search-fuzzy "<core>" --threshold 0.6
   python3 -m vostlit_research by-region Дагестан "<core>"
   ```
4. **Read context** for every hit:
   ```bash
   python3 -m vostlit_research context <section_id> --before 2 --after 2
   ```
5. **Source criticism** per cited source:
   ```bash
   python3 -m vostlit_research document <id>
   python3 -m vostlit_research bibliography <id>
   ```
   Check: document date vs. publication year; author; edition; translator;
   region/period fit.
6. **Triangulate**:
   ```bash
   python3 -m vostlit_research compare "<claim>" <id1> <id2> <id3>
   ```
   Decide independence (two excerpts from one chronicle = one witness).
7. **Find mentions** of a name across the corpus:
   ```bash
   python3 -m vostlit_research mentions "<name>"
   ```

## Phase 4 — Answer

Use the required format (Краткий вывод / Найденные источники / Дословные
свидетельства / Анализ / Альтернативы / Итоговая оценка / Следующие шаги).
Cite `document_id`+`section_id`+`canonical_url` for every quote. Mark OCR
uncertainty. If the corpus is silent, say **Не установлено** and propose the
next crawl — never invent.

## Phase 5 — (Optional) record the conclusion

If the workflow calls for it, persist a research note:

```bash
python3 - <<'PY'
from vostlit_research.config import Config
from vostlit_research.db import Database
from vostlit_research.io import upsert_research_note
from vostlit_research.models import ResearchNoteIn, FragmentRef
cfg = Config(); db = Database(cfg.db_path)
upsert_research_note(db, ResearchNoteIn(
    claim="...",
    status="hypothesis",   # source_fact | interpretation | hypothesis | refuted
    supporting_fragments=[FragmentRef(section_id=487, document_id=7, quote="...", url="...")],
    confidence="possible",
))
db.close()
PY
```

A note's `status` is explicit; hypotheses never auto-promote to facts.

## Anti-patterns (do not)

- Citing a fragment you did not read in context.
- Treating a fuzzy candidate as a confirmed identity.
- Merging toponyms on string similarity alone.
- Answering from model memory when a source check is possible.
- Claiming the event "did not happen" because the corpus is silent.
