# SEARCH AUDIT — vostlit-research search-engine quality

> Task ID: **C-search**
> Agent: retrieval-engineer
> Date: 2025-10-27 (Europe/Moscow)
> Scope: read-only audit of `vostlit_research/search/{engine,fts,semantic}.py` and
> `vostlit_research/textnorm.py` against the seeded corpus
> (`data/vostlit.db`, 10 fixture docs / 661 sections / 5 entities / 4 name-variants).
> **No code was modified.** All claims are reproducible from the command blocks
> cited inline; raw audit output is preserved at `/home/z/audit_output.txt`.

---

## 1. Method

1. Read `engine.py`, `textnorm.py`, `fts.py`, `semantic.py`, `research/api.py`,
   `schema.sql`, `models.py`, `config.py`, `tests/test_search.py`,
   `tests/test_v02_improvements.py`, `scripts/seed_corpus.py`,
   `references/historical-toponyms.md`, `docs/UPGRADE_BASELINE.md`, `worklog.md`.
2. Verified the live DB state: `python3 -c "..."` against `data/vostlit.db`
   (10 docs, 661 sections, 5 entities, 4 variants — exactly the seeded corpus).
3. Wrote a single audit harness `/home/z/audit_search.py` that runs all
   verification queries and prints citable output. Saved raw output to
   `/home/z/audit_output.txt`.
4. Cross-checked audit harness output with direct one-liner SQL probes
   (region case-sensitivity, COALESCE date behaviour, body-search for
   "Гумбет"/"Салатавия", fts_documents population, filter bypass).
5. Mapped the 12 master-prompt §6.1 pipeline stages to actual code; flagged
   stubs and missing strategies.
6. Defined 8 reproducible benchmark scenarios and ran them live; recorded
   pass/fail.

Citation convention: `engine.py:181` means `vostlit_research/search/engine.py`
line 181.

---

## 2. Pipeline-stage coverage (§6.1, 12 stages)

| # | Stage | Implemented? | File:line | Quality note |
|---|---|---|---|---|
| 1 | **exact phrase** | ✅ real | `engine.py:181-215` | SQL `LIKE %needle%` on `text_lower` (Cyrillic-aware lower, ё preserved); snippet via offset-preserving `fold_for_match`. ✓ |
| 2 | **FTS5 ranked** | ✅ real | `engine.py:218-255`; `fts.py:13-30` | `bm25(fts_sections)` over normalised `heading_norm`+`text_norm`. ✓ |
| 3 | **normalised** | ✅ implicit | `textnorm.py:107-126` | Not a separate strategy — folded into FTS, fuzzy, and `_locate_and_snippet`. ✓ |
| 4 | **name-variant** | ✅ real | `engine.py:258-320` | Dict lookup on `original_form` + `normalized_form` + FTS over `fts_name_variants`. ✓ |
| 5 | **pre-reform / ё fold** | ✅ real | `textnorm.py:80-91, 107-126` | `fold_pre_reform` (ѣ→е, і→и, ѳ→ф, ѵ→и) + `fold_yo` (ё→е). ✓ verified live (§3). |
| 6 | **transliteration** | ⚠️ partial | `engine.py:258-320` (variant_type='transliteration' supported by schema `schema.sql:128`) | No dedicated strategy — only dictionary variants with `variant_type='transliteration'` are found. **Novel transliterations not in the dictionary are missed** (fuzzy normalises both sides, no G→Г map). |
| 7 | **OCR-error** | ❌ **MISSING** | — | Schema allows `variant_type='ocr_error'` (`schema.sql:128`), but `grep -rni 'ocr\|levenshtein\|edit_distance\|ngram'` finds **0 strategy code**. No edit-distance, no confusion matrix, no n-gram. |
| 8 | **geographic-generic strip** | ✅ real | `textnorm.py:47-67, 211-222`; `engine.py:428-504` | `strip_geo_generic` + `search_toponym`. ✓ verified live (§5). |
| 9 | **filters (region/author/date/type)** | ⚠️ partial | `engine.py:77-108` | Filter **only applied** in `search_exact` (l. 185) and `search` (l. 222). **Dropped on the floor** in `search_variants` (l. 258 — `filters` param never used) and `search_fuzzy` (l. 323 — `filters` param never used). See §7. |
| 10 | **notes/biblio search** | ⚠️ partial | `engine.py:218-255` (sections only); `research/api.py:76-88` (`get_document_bibliography`) | Notes (`section_type='note'`, 110 rows) ARE indexed in `fts_sections` and searchable via `eng.search()`. BUT `fts_documents` (which holds `bibliography_norm`, populated for 5/10 docs) is **never queried by the engine** — `fts_match_documents` is defined in `fts.py:33` but has **zero call sites** in `engine.py`/`api.py`. Bibliography-only queries return nothing. |
| 11 | **candidate-relations** | ❌ **MISSING** | — | `grep -rni 'candidate_relation\|work_relation\|entity_relation\|CREATE TABLE.*relations'` → 0 matches. Confirmed in `UPGRADE_BASELINE.md:103-104`: "Связи между произведениями основаны ТОЛЬКО на общем URL-префиксе (`_work_prefix`); нет отдельной таблицы связей с типом и доказательством." |
| 12 | **semantic** | ⚠️ honest no-op | `semantic.py:31-35, 42-57` | `NoopSemanticProvider` returns `[]`; pluggable interface exists. `engine.py:388-389` calls it. Honest (no fake vectors). |

**Summary**: 6 of 12 stages fully implemented and live-verified; 3 partial
(#6 transliteration, #9 filters, #10 notes/biblio); 1 honest stub (#12
semantic — by design); **2 outright missing** (#7 OCR-error, #11
candidate-relations).

---

## 3. Pre-reform / ё / case verification — live output

### 3.1 Unit-level fold (textnorm)

```
$ python3 /home/z/audit_search.py   # section A
[і→и] q='Салатавія' target='Салатавия'
    normalise_search(q)='салатавия'  normalise_search(target)='салатавия'
    fold_for_match substring hit: True  | normalised substring hit: True
[ё→е] q='ёлка' target='елка'
    normalise_search(q)='елка'  normalise_search(target)='елка'
    fold_for_match substring hit: True  | normalised substring hit: True
[ъ dropped (token-level)] q='Дагестанъ' target='Дагестан'
    normalise_search(q)='дагестан'  normalise_search(target)='дагестан'
    fold_for_match substring hit: False | normalised substring hit: True
[inflected form via substring fold] q='Дагестан' target='дагестанских'
    normalise_search(q)='дагестан'  normalise_search(target)='дагестанских'
    fold_for_match substring hit: True  | normalised substring hit: True
```

**Verdict**: `normalise_search` correctly folds ѣ→е, і→и, ѳ→ф, ѵ→и, ё→е, and
drops ъ at the token level (`textnorm.py:107-126`). The 1:1 `fold_for_match`
(`textnorm.py:278-290`) intentionally does **not** drop ъ (preserves offsets);
the docstring at `textnorm.py:262-275` explains this trade-off — ъ-mismatches
are caught at the token level by FTS, not by the substring locator. So
"Дагестанъ" vs "Дагестан" fails the substring `fold_for_match` (ъ is kept,
offsets preserved) but matches at the normalised level. **No defect** —
documented behaviour.

### 3.2 Live FTS search against the seeded corpus

```
$ python3 /home/z/audit_search.py   # section B
eng.search('Салатавія') -> 0 hits
eng.search('Салатавия') -> 0 hits
eng.search('ёлка')      -> 0 hits
eng.search('елка')      -> 0 hits
eng.search('Дагестан')  -> 3 hits; top doc=8, sec=556
    snippet: '"ТАРИХ-И ДАГЕСТАН" МУХАММАДРАФИ'
```

**Important finding**: searching "Салатавія" (і) or "Салатавия" (modern)
against the **seeded fixture corpus** returns **0 FTS hits** — not because
the fold is broken (§3.1 proves it works), but because the seeded corpus has
**no body-text occurrence of "Салатавия"**. Verified directly:

```
$ python3 -c "..."    # see /home/z/audit_output.txt
=== Body search for Салатавия ===
(no rows)
```

The existing test `test_fts_search_folds_yo_and_prereform`
(`tests/test_search.py:51-62`) passes because it uses its **own in-test seed**
(`tests/test_search.py:10-29`) which puts "Салатавия" in the doc body
directly. That test does **not** run against the seeded fixture corpus. So
the fold mechanism is verified correct, but there is no end-to-end
demonstration of і→и search against the real Vostlit fixture content.

**Recommendation**: extend `seed_corpus.py` to include at least one fixture
whose body actually contains a pre-reform spelling (ѣ or і), so the
end-to-end fold is observable in the seeded DB.

### 3.3 Case + inflection via `search_exact` — verified live

```
$ python3 /home/z/audit_search.py   # section C
eng.search_exact('Дагестан')   -> 15 hits; docs=[7, 8]
eng.search_exact('дагестан')   -> 15 hits; docs=[7, 8]
eng.search_exact('ДАГЕСТАН')   -> 15 hits; docs=[7, 8]
eng.search_exact('дагестанск') -> 9 hits; docs=[7]
    ** section 487 hit: snippet='К вопросу о вхождении дагестанских владельцев в состав России. 1792 г.'
```

**Verdict**: `search_exact` is case-insensitive (via `text_lower` column,
`engine.py:189-190`) and **finds inflected forms** ("дагестанск" matches
"дагестанских"). The substring fold at `engine.py:131-170` works as
documented. ✓

**Test citation**: `tests/test_search.py:41-48`
(`test_exact_search_preserves_spelling_and_finds_phrase`).

---

## 4. Fuzzy threshold calibration report

Default threshold = `0.72` (`engine.py:323`, `textnorm.py:186`).

### 4.1 Real-name probe (threshold = 0.72, default)

```
$ python3 /home/z/audit_search.py   # section D
fuzzy('Гумбет'   , t=0.72) -> 2 matches  (Гумбетъ=1.000, Гумбет=1.000)   ✓ true positives
fuzzy('Гумбете'  , t=0.72) -> 2 matches  (0.923)                          ✓ seeded variant
fuzzy('Гумбетъ'  , t=0.72) -> 2 matches  (1.000)                          ✓ pre-reform
fuzzy('Гумбетт'  , t=0.72) -> 2 matches  (0.923)                          ✓ typo
fuzzy('Гумбат'   , t=0.72) -> 2 matches  (0.833)                          ✓ alt transliteration
fuzzy('Кумбет'   , t=0.72) -> 2 matches  (0.833)                          ✓ K/G confusion
fuzzy('Губет'    , t=0.72) -> 2 matches  (0.909)                          ✓ missing letter
fuzzy('Гумбетия' , t=0.72) -> 2 matches  (0.857)                          ⚠ FALSE POSITIVE (different place)
fuzzy('Салатавия', t=0.72) -> 3 matches  (Салатавія=1.000, Салатавия=1.000, Салатав=0.875)  ✓
fuzzy('Чечня'    , t=0.72) -> 0 matches                                    ✓ true negative
fuzzy('Андийское общество', t=0.72) -> 0 matches                          ✓ true negative
```

### 4.2 Threshold sweep for "Гумбет"

```
$ python3 /home/z/audit_search.py   # section D2
t=0.5:  2 matches  -> Гумбетъ=1.000, Гумбет=1.000
t=0.6:  2 matches  -> Гумбетъ=1.000, Гумбет=1.000
t=0.72: 2 matches  -> Гумбетъ=1.000, Гумбет=1.000
t=0.8:  2 matches  -> Гумбетъ=1.000, Гумбет=1.000
t=0.9:  2 matches  -> Гумбетъ=1.000, Гумбет=1.000
t=1.0:  2 matches  -> Гумбетъ=1.000, Гумбет=1.000
```

### 4.3 Calibration assessment

- The default 0.72 is **calibrated for short (5-7 char) Russian names**:
  it correctly catches single-character typos, missing letters, and
  K/G transliteration confusion (all in 0.83-0.93 range).
- **False positive observed**: "Гумбетия" (a different place name, +2 chars
  suffix "-ия") scores 0.857 — above threshold. The fuzzy matcher has no
  notion of suffix morphology, so any name that happens to share a 6-char
  stem passes.
- The threshold sweep shows the dictionary is so small (4 variants + 5
  entities) that **all candidates score either 1.000 (exact) or 0.83+**;
  there's no "near-miss below threshold" to discriminate. A real
  threshold-calibration run needs a much larger variant dictionary
  (≥100 entries) before 0.72 can be defended or refined.
- **All fuzzy results are correctly marked `confidence='candidate'` and
  carry the "NOT a confirmed identity" disclaimer** (`engine.py:358, 377`).
  ✓

**Recommendation**: bump the default to 0.80 (rejects "Гумбетия"-style
suffix extensions) OR introduce a length-aware penalty (e.g. require
`score >= 0.72 AND |len(q) - len(cand)| <= 2`). Calibrate against a real
100+ variant dictionary before ship.

---

## 5. Toponym generic-term audit

### 5.1 Live strip output

```
$ python3 /home/z/audit_search.py   # section E
strip_geo_generic('гора Джалдари-меер'      ) -> 'джалдари'        ✓ (меер stripped; hyphen-split by _WORD_RE)
strip_geo_generic('Гора Гумбет'             ) -> 'гумбет'          ✓
strip_geo_generic('гора Гумбетъ'            ) -> 'гумбет'          ✓
strip_geo_generic('хребет Салават'          ) -> 'салават'         ✓
strip_geo_generic('урочище у горы Джалдари' ) -> 'у джалдари'      ⚠ preposition "у" kept
strip_geo_generic('озеро Мехтуб'            ) -> 'мехтуб'          ✓
strip_geo_generic('река Сулак'              ) -> 'сулак'           ✓
strip_geo_generic('крепость Тарки'          ) -> 'тарки'           ✓
strip_geo_generic('маги КӀудияб'            ) -> 'кӏудияб'         ✓ (маги stripped; Ӏ→ӏ by NFKC)
strip_geo_generic('крепость Дербента'       ) -> 'дербента'        ✓
```

The master-prompt example `strip_geo_generic("гора Джалдари-меер") =
"джалдари"` is reproduced exactly. ✓

### 5.2 Source-attestation audit of the Dagestan-specific generics

The list at `textnorm.py:62-63` adds three non-Russian generics:

| Term | In `references/historical-toponyms.md`? | In seeded corpus body? | Verdict |
|---|---|---|---|
| **меер** | ✅ yes — §1 (l. 19), §2 (l. 34-35): *"Dagestani/Caucasian: **меер** (mountain/peak — appears in names like Джалдари-меер)"* | ❌ 0 section hits | **Source-attested** (in the project's own reference doc); not yet corpus-attested. Acceptable. |
| **маги** | ❌ NOT mentioned in `references/historical-toponyms.md` | ⚠ 5 substring hits but all are **false-positive substrings** inside other words (e.g. "поражением", "замечая" — the substring "маги" matches inside Russian words due to no word-boundary check). 0 hits on `Маги` (capital). | **Speculative / unattested.** Flag for removal or scholarly citation. |
| **кӀудияб** | ❌ NOT mentioned in `references/historical-toponyms.md` | ❌ 0 section hits (any case) | **Speculative AND wrong**: `кӀудияб` is the Avar adjective "большой" (big/large), not a geographic generic. Including it would cause `strip_geo_generic` to delete "кӀудияб" from any toponym where it appears as a size modifier. Flag for removal. |

**Recommendation**: keep `меер` (attested in the project's reference doc);
**remove `маги` and `кӀудияб`** from `GEO_GENERIC_TERMS` unless a scholarly
citation is added to `references/historical-toponyms.md`. Add a unit test
that asserts every entry in `GEO_GENERIC_TERMS` is either (a) attested in
`references/historical-toponyms.md` or (b) accompanied by an inline comment
citing a source.

### 5.3 Minor side-effect

`strip_geo_generic` keeps function words: `"урочище у горы Джалдари"` →
`"у джалдари"` (the preposition "у" survives). This is harmless for fuzzy
core-matching but produces an unexpected core string. Optional: also strip a
small stop-word list (у, на, в, во, из, от, к, по).

---

## 6. Ranking correctness

### 6.1 Live `search_hybrid` output

```
$ python3 /home/z/audit_search.py   # section F
hybrid('Дагестан'):
    score=1001.000  match_type=hybrid  doc=7  sec=487  conf=verified    snippet='К вопросу о вхождении дагестанских владельцев...'
    score=1001.000  match_type=hybrid  doc=7  sec=488  conf=verified    snippet='Вхождение Дагестана в состав России происходило...'
    ...8 exact hits, all score 1001, all doc 7...

hybrid('Гумбет'):
    score= 501.000  match_type=hybrid  doc=0  sec=None  conf=candidate  snippet='Гумбетъ'
    score=   2.000  match_type=hybrid  doc=0  sec=None  conf=candidate  snippet='Гумбетъ'
    (no exact hit — "Гумбет" is not in any section body of the seeded corpus)
```

### 6.2 Ranking-bucket analysis

`search_hybrid` (`engine.py:392-425`) assigns scores:
- exact  → `1000 + r.score`  (`engine.py:405`)  → 1001
- variant → `500 + r.score`  (`engine.py:407`)  → 501
- fts    → `10 + bonus + 1/(1+|bm25|)`  (`engine.py:411`)  → ~10-11
- fuzzy  → `1 + r.score`     (`engine.py:413`)  → 1.00-2.00
- semantic → `0.5`           (`engine.py:416`)

**For "Дагестан"** (which has body attestations): exact hits at 1001
correctly dominate the 8-result list. ✓
**For "Гумбет"** (no body attestation in seeded corpus): the top hit is a
variant match at 501 — no exact hit to outrank it. **The bucket dedup key
`(document_id, section_id, match_type)` at `engine.py:420` collapses all
variant rows with `doc=0, sec=None` to ONE bucket**, so only 1 variant hit
survives despite 1 variant + 1 entity both matching. Result list = 2 (one
variant-bucket, one fuzzy-bucket), all with `doc=0` (no verifiable source).

### 6.3 "Does an exact source quote always outrank a fuzzy candidate?"

**Yes — when an exact hit exists.** `engine.py:405` gives exact `1000+r.score`
≥ 1001; `engine.py:413` gives fuzzy `1+r.score` ≤ 2. The 1000-point gap
guarantees exact > fuzzy regardless of fuzzy similarity.

**Test citation**: `tests/test_search.py:106-115`
(`test_hybrid_ranks_exact_above_fuzzy`):

```python
def test_hybrid_ranks_exact_above_fuzzy(tmp_db):
    _seed(tmp_db)
    eng = SearchEngine(tmp_db)
    res = eng.search_hybrid("Гумбет")
    assert res
    exact_scores = [r.score for r in res if r.match_type in ("exact", "variant")]
    fuzzy_scores = [r.score for r in res if r.match_type == "fuzzy"]
    if exact_scores and fuzzy_scores:
        assert max(exact_scores) >= max(fuzzy_scores)
```

**Caveat (test-coverage gap)**: the assertion is guarded by `if exact_scores
and fuzzy_scores:` — if either list is empty (as happens against the seeded
corpus, where "Гумбет" produces 0 exact hits), the test **silently passes
without exercising the ranking claim**. The test only proves ranking when
both buckets are non-empty, which requires the in-test seed at
`test_search.py:10-29` (which DOES put "Гумбет" in the body). The test does
not run against the seeded fixture corpus. **Recommendation**: add an
unconditional `assert max(exact_scores) > max(fuzzy_scores)` whenever both
are non-empty, AND add a benchmark scenario B5 (below) that runs against the
seeded corpus.

---

## 7. Filter defects found

### 7.1 Defect F1 — `search_variants` and `search_fuzzy` silently ignore filters

**Code**: `engine.py:258-320` (`search_variants`) and `engine.py:323-380`
(`search_fuzzy`) both accept a `filters` parameter but **never call
`_allowed_doc_ids` or `_filters_where`** with it. The parameter is dead.
`grep -n 'filters'` over `search_variants` body: only the signature and the
docstring.

Additionally `search_toponym` (`engine.py:488`) calls
`self.search_variants(form, limit=limit)` — **without passing `filters`** —
so even if `search_variants` honoured filters, `search_toponym` would drop
them for the variant step.

**Reproduction** (filter excludes ALL docs in the corpus):

```
$ python3 -c "..."   # see /home/z/audit_output.txt
=== search_variants('Гумбетъ', filters=region=Несуществующий_Регион) ===
  filter excludes ALL docs, but search_variants returns: 1 results
    -> snippet='Гумбетъ' doc_id=0 title='Гумбет'

=== search_fuzzy('Гумбет', filters=region=Несуществующий_Регион) ===
  filter excludes ALL docs, but search_fuzzy returns: 2 results

=== search_hybrid('Дагестан', filters=region=Несуществующий) ===
  hybrid returns: 2 results
  exact (score>=1000): 0, variant (500-999): 1, fuzzy (<100): 1
  (exact hits ARE filter-conformant; variant+fuzzy are NOT)
```

For "Дагестан" with a bogus region filter: the 8 exact hits are correctly
filtered out (because `search_exact` honours `_allowed_doc_ids`), but the
variant and fuzzy buckets still return their `doc=0` results, so the hybrid
list is non-empty despite the filter excluding all documents. The user
asks "give me Дагестан hits in region X" and gets dictionary-only candidates
with no source attestation.

**Severity**: high — silently breaks the filter contract for `search_hybrid`
and `search_toponym`. **Recommendation**: in `search_variants` and
`search_fuzzy`, after assembling candidates, drop any whose
`evidence_section_id`/`document_id` is not in `_allowed_doc_ids(db, f)` (or
mark them with `confidence='candidate'` and a `note='filter not applied:
dictionary-only'`).

### 7.2 Defect F2 — Cyrillic case-sensitivity in region filter (and author filter)

**Code**: `engine.py:84` uses `d.region LIKE ?` with param `f"%{f.region}%"`.
SQLite's `LIKE` is **ASCII-case-insensitive only** — it does NOT fold
Cyrillic case. So `region='кавказ'` (lowercase) fails to match a doc whose
`region='Кавказ'`.

`engine.py:87` uses `LOWER(d.author) LIKE LOWER(?)` — this LOOKS
case-insensitive, but SQLite's `LOWER()` is also ASCII-only, so it leaves
Cyrillic capitals untouched. Same defect.

**Reproduction**:

```
$ python3 -c "..."   # see /home/z/audit_output.txt
=== Region filter case sensitivity (SQL the engine uses) ===
  region LIKE %Кавказ%  -> [{'id': 10, 'region': 'Кавказ'}]      ✓ capital matches
  region LIKE %кавказ%  -> []                                     ✗ lowercase does NOT match
  region LIKE %КАВКАЗ%  -> []                                     ✗ all-caps does NOT match
  region LIKE %Дагестан% -> [{'id': 7, ...}, {'id': 8, ...}]     ✓
  region LIKE %дагестан% -> []                                     ✗

=== Author filter (uses LOWER) ===
  LOWER(author) LIKE LOWER(%ИОРДАН%) -> [{'id': 2, 'author': 'ИОРДАН'}]   ✓ (matches itself)
  LOWER(author) LIKE LOWER(%иордан%) -> []                                 ✗ lowercase does NOT match
  LOWER(author) LIKE LOWER(%Иордан%) -> []                                 ✗ mixed case does NOT match
```

**Why the existing tests don't catch this**: `tests/test_search.py:85-92`
(`test_filter_by_region`) tests with `region='Дагестан'` and `region='Кавказ'`
— both with the EXACT capitalisation that matches the seeded docs. There is
no test with `region='дагестан'` or `region='ДАГЕСТАН'`.

**Severity**: high — user-supplied region/author strings (e.g. from a CLI
flag) will silently return 0 results if the case differs from the stored
value. **Recommendation**: replace `LIKE` with `textnorm.fold_for_match(d.region) LIKE textnorm.fold_for_match(?)` (or store a pre-folded `region_norm` column and index that). Add a regression test with `region='дагестан'`.

### 7.3 Defect F3 — date filter is lexicographic and uses `publication_year` first

**Code**: `engine.py:92-97`:

```python
if f.date_from:
    clauses.append("COALESCE(d.publication_year, d.original_creation_date, '') >= ?")
    params.append(f.date_from)
if f.date_to:
    clauses.append("COALESCE(d.publication_year, d.original_creation_date, '') <= ?")
    params.append(f.date_to)
```

Two problems:

**(a) Lexicographic, not numeric, comparison.** `publication_year` is
declared `TEXT` (`schema.sql:41`) because years can be ranges ("1792-1801")
or circa ("circa 1839"). But `>= ?` on TEXT compares code-point by
code-point. So:

```
TEXT '900'   >= '1792' : True   (WRONG — '9' > '1' as chars; 900 < 1792 numerically)
TEXT '1792'  >= '800'  : False  (WRONG — '1' < '8' as chars; 1792 > 800 numerically)
TEXT '1792'  >= '1800' : False  (correct by coincidence — both 4-digit)
TEXT '1792-1801' >= '1792' : True  (range prefix matches; OK by accident)
TEXT 'circa 1839' >= '1839' : True  ('c' > '1' as chars; semantically nonsensical)
TEXT '1839'   >= '1839 г.' : False (suffix breaks equality)
```

For 4-digit-only years the bug is invisible; for any year < 1000, ranges,
circa, or trailing text, it's wrong.

**(b) `COALESCE(publication_year, original_creation_date, '')` prefers
publication_year.** For a historical-source system, `publication_year` is
the modern edition's year (e.g. 2003) and `original_creation_date` is when
the source was actually written (e.g. 1792). The user filtering by
`date_from=1792 date_to=1800` wants sources **written** in that period, not
modern editions published then.

**Reproduction** against the seeded corpus:

```
$ python3 -c "..."   # see /home/z/audit_output.txt
COALESCE(publication_year, original_creation_date, '') per doc:
  doc 7: pub_year='2003' orig_date='1792' -> coalesce='2003'   ← wrong field picked
  doc 2: pub_year='1997' orig_date=None   -> coalesce='1997'
  ...

_allowed_doc_ids for date 1792-1800: set()   ← empty, excludes all 10 docs

Real corpus: ResearchEngine.search_by_date(date_from='1792', date_to='1800'):
  (n=0)    ← doc 7 (the 1792 source) is NOT found

Real corpus: search_by_date(date_from='2003', date_to='2003'):
  doc=7  year='2003'    ← only matches because pub_year=2003
```

So `search_by_date("1792", "1800")` returns 0 docs even though doc 7 is a
primary source from 1792. The user asking "show me sources written around
the 1792 treaty" gets nothing.

**Severity**: high for historical research workflows — the date filter
answers the wrong question. **Recommendation**:
1. Filter on `original_creation_date` when present (fall back to
   `publication_year` only if `original_creation_date` is NULL).
2. Extract the first 4-digit year from the value and compare as INTEGER
   (`CAST(substr(COALESCE(original_creation_date, publication_year, ''), 1, 4) AS INTEGER)`),
   so "circa 1839" and "1792-1801" both work.
3. Add a regression test: `search_by_date("1790", "1800")` MUST return doc 7.

---

## 8. Benchmark scenarios — live run against seeded corpus

Each scenario is reproducible by running the python snippet in §I of
`/home/z/audit_search.py`. The seeded corpus is `data/vostlit.db`
(10 fixture docs / 661 sections / 5 entities / 4 variants).

| ID | Query (method, args) | Expected | Actual | Pass/Fail |
|---|---|---|---|---|
| **B1** | `search_exact("дагестанск")` | returns doc 7, section 487 | `doc=7 sec=487 score=1.0 snippet='К вопросу о вхождении дагестанских владельцев...'` (+ 8 more sec hits in doc 7) | ✅ PASS |
| **B2** | `search_exact("Гумбет")` | ≥1 result with snippet containing "Гумбет" | **0 results** — "Гумбет" is not in any section body of the seeded corpus (verified: `SELECT * FROM document_sections WHERE text LIKE '%Гумбет%'` → 0 rows) | ❌ FAIL (corpus gap, not engine bug) |
| **B3** | `eng.search("Салатавія")` (FTS, і→и fold) | ≥1 FTS hit | **0 hits** — "Салатавія"/"Салатавия" not in any section body. The fold is correct (§3.1) but there's no body occurrence to find. | ❌ FAIL (corpus gap) |
| **B4** | `search_variants("Салатавія")` | returns the variant `original_form='Салатавія'` linked to entity `Салатавия` | `title='Салатавия' snippet='Салатавія' ctx_after='normalised=салатавия; type=historical; status=candidate'` | ✅ PASS |
| **B5** | `search_hybrid("Гумбет")` | exact hit (score 1001) outranks any fuzzy candidate (score <2) | only 2 results: variant@501 + fuzzy@2.0, both `doc=0 sec=None`. No exact hit exists, so the ranking claim cannot be tested against this corpus. | ❌ FAIL (corpus gap — exact-outranks-fuzzy is verified only in the in-test seed at `test_search.py:106-115`) |
| **B6** | `search_toponym("гора Гумбет")` | `core_toponym='гумбет'`; ≥1 candidate with verifiable `source_url` | `core_toponym='гумбет' ✓; forms=['гора Гумбет','гумбет'] ✓; n_candidates=2`; **but both candidates have `document_id=0, section_id=None, source_url=''`** — they are dictionary-only, not source-grounded. | ⚠ PARTIAL (core decomposition correct; verifiable-source requirement not met) |
| **B7** | `search_fuzzy("Гумбет")` | all results `confidence='candidate'` and `"NOT a confirmed identity"` in explanation | `score=1.000 conf=candidate snippet='Гумбетъ' why='fuzzy candidate (similarity=1.00) — NOT a confirmed identity'` (+ entity match) | ✅ PASS |
| **B8** | `search_hybrid("Гумбет", SearchFilters(date_from="1792", date_to="1800"))` | returns only doc 7 (the 1792 source) | 2 results, both `doc=0 year=None` — these are variant/fuzzy candidates that **bypass the date filter** (defect F1). Doc 7 is excluded by defect F3 (COALESCE picks `publication_year=2003`, which is outside 1792-1800). | ❌ FAIL (two compounding defects: F1 + F3) |
| **B-extra** | `search_by_date("1792", "1800")` (no query) | doc 7 should be returned (original_creation_date=1792) | **0 docs** — `COALESCE(publication_year, original_creation_date, '')` returns `'2003'` for doc 7, which fails `<= '1800'`. | ❌ FAIL (defect F3) |

**Pass/fail tally**: 3 PASS, 5 FAIL/PARTIAL out of 8 scenarios (+1 extra).

**Of the 5 failures**:
- 3 are **corpus gaps** (B2, B3, B5) — the seeded fixture corpus lacks body
  occurrences of "Гумбет" and "Салатавия". Fix: extend `seed_corpus.py` or
  run `crawl --region caucasus --limit 25` to add real Vostlit pages.
- 2 are **engine defects** (B6 partial, B8 + B-extra) — filter bypass (F1)
  and date COALESCE (F3).

---

## 9. Recommendations (ordered by impact)

### P0 — Fix engine defects (silently wrong results)

1. **F1 — Apply filters in `search_variants` and `search_fuzzy`**
   (`engine.py:258, 323`). After assembling candidates, drop any whose
   `evidence_section_id`/`document_id` is not in `_allowed_doc_ids(db, f)`.
   Pass `filters` through `search_toponym`'s variant call (`engine.py:488`).
   Add a regression test: `search_hybrid("Дагестан",
   SearchFilters(region="Несуществующий"))` MUST return `[]`.

2. **F2 — Cyrillic-aware region/author filter** (`engine.py:84, 87`).
   Replace `LIKE` with `fold_for_match(d.region) LIKE fold_for_match(?)`
   (or add a `region_norm` column populated on insert and index that).
   Add a regression test: `search_exact("Гумбет",
   SearchFilters(region="дагестан"))` MUST return the same docs as
   `region="Дагестан"`.

3. **F3 — Date filter: switch to `original_creation_date` first + integer
   parse** (`engine.py:92-97`). Use
   `CAST(substr(COALESCE(original_creation_date, publication_year, ''), 1, 4) AS INTEGER)`
   and numeric comparison. Add a regression test: `search_by_date("1790",
   "1800")` MUST include doc 7.

### P1 — Close pipeline gaps

4. **#7 OCR-error strategy**. Add a character-level edit-distance matcher
   (Levenshtein ≤ 2 for names ≤ 8 chars; ≤ 3 for longer) over the
   `name_variants.original_form` column. Mark results `confidence='candidate'`
   with disclaimer. Schema already supports `variant_type='ocr_error'`
   (`schema.sql:128`) — populate it from the matcher.

5. **#11 Candidate-relations strategy**. Add a `work_relations` table
   (source_doc_id, target_doc_id, relation_type, evidence_section_id,
   confidence) and a `search_relations(document_id)` method. The current
   `_work_prefix` URL-grouping (`cli.py`) is a heuristic, not evidence-based.

6. **#10 Wire `fts_documents` into the engine**. `fts_match_documents`
   (`fts.py:33`) is defined but never called. Add a `search_documents`
   method that merges `fts_documents` hits (title/author/bibliography)
   into `search_hybrid` at score ~100 (between fts-sections and fuzzy).
   Bibliography-only queries ("Русско-дагестанские отношения") currently
   return nothing despite `fts_documents` being populated.

### P2 — Calibration and corpus quality

7. **Bump fuzzy default threshold to 0.80 OR add a length-aware penalty**
   (`engine.py:323`). At 0.72, "Гумбетия" (a different place) scores 0.857
   and passes. Calibrate against a real 100+ variant dictionary before
   ship.

8. **Extend `seed_corpus.py`** to include at least one fixture whose body
   contains a pre-reform spelling (ѣ or і) and one that mentions "Гумбет"
   / "Салатавия" verbatim. This unblocks benchmarks B2, B3, B5 and gives
   end-to-end demonstration of the і→и / ё→е fold against real Vostlit
   content.

9. **Remove speculative geo-generics `маги` and `кӀудияб`** from
   `GEO_GENERIC_TERMS` (`textnorm.py:63`). `кӀудияб` is the Avar adjective
   "big", not a geographic generic. Add a unit test that asserts every
   list entry is attested in `references/historical-toponyms.md` or has
   an inline source citation.

### P3 — Test-coverage gaps

10. **Tighten `test_hybrid_ranks_exact_above_fuzzy`**
    (`tests/test_search.py:106-115`). The current `if exact_scores and
    fuzzy_scores:` guard silently passes when either bucket is empty.
    Add a separate test that asserts the bucket is non-empty against the
    seeded corpus (after fixing #8).

11. **Add a regression suite for the 8 benchmark scenarios in §8** as
    `tests/test_search_benchmarks.py`, run against the seeded DB. These
    become the contract: any change to `engine.py` or `textnorm.py` that
    breaks a benchmark scenario fails CI.

---

## Appendix A — Files inspected

- `vostlit_research/search/engine.py` (505 lines)
- `vostlit_research/search/fts.py` (66 lines)
- `vostlit_research/search/semantic.py` (62 lines)
- `vostlit_research/textnorm.py` (291 lines)
- `vostlit_research/research/api.py` (305 lines)
- `vostlit_research/schema.sql` (236 lines)
- `vostlit_research/models.py`, `config.py`, `store.py`, `io.py`
- `tests/test_search.py` (153 lines), `tests/test_v02_improvements.py` (253 lines),
  `tests/conftest.py`
- `scripts/seed_corpus.py`, `scripts/search.py`, `scripts/mountain_search.py`
- `references/historical-toponyms.md`
- `docs/UPGRADE_BASELINE.md`
- `worklog.md` (tasks 0, 1-site, main-final, v02-improvements)

## Appendix B — Reproduction

The audit harness lives at `/home/z/audit_search.py` (outside the repo to
honour the "no code modification" constraint). Raw output is at
`/home/z/audit_output.txt`. To reproduce:

```sh
cd /home/z/my-project/vostlit-research
python3 /home/z/audit_search.py | tee /home/z/audit_output.txt
```

To re-verify any individual claim, the inline code blocks in §3-§8 are
copy-paste runnable against the seeded DB.
