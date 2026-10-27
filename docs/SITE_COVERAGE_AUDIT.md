# SITE_COVERAGE_AUDIT.md — How completely can the current system discover & ingest the vostlit.info corpus?

> A **factual coverage audit** of the `vostlit-research` discovery + ingest
> pipeline against the real `https://www.vostlit.info/` site. Every claim is
> marked **[verified]** (opened during this audit or in the SITE_AUDIT.md
> fixtures) or **[assumption]** (inferred from code, not opened). No counts
> are invented.
>
> Companion to `docs/SITE_AUDIT.md` (structural page anatomy) and
> `docs/UPGRADE_BASELINE.md` (code-level defects). This doc focuses on
> **coverage**: which entry points, regions, collections, and page types the
> current `discover.py` + `crawl.py` + `parser.py` can actually reach, fetch,
> and parse — and where it silently drops content.

---

## 1. Method & date

- **Date:** 2025-10-27 (Europe/Moscow, UTC+3).
- **Method:**
  1. Read `worklog.md`, `UPGRADE_BASELINE.md`, `SITE_AUDIT.md` (prior
     findings) and the live code (`discover.py`, `crawl.py`, `parser.py`,
     `http.py`, `config.py`, `seed_corpus.py`, `cli.py`).
  2. Re-used the 13 existing fixtures (`tests/fixtures/`, sha256-verified
     in `fixtures_manifest.json`) — did **not** re-fetch pages already
     captured there.
  3. Queried the persistent DB at `data/vostlit.db` (3.0 MB) for real
     status / page_type / crawl_log counts.
  4. Fetched **15 new live pages** with `httpx` 0.28.1, UA
     `Mozilla/5.0 (compatible; vostlit-research-audit/0.1)`, 30 s timeout,
     `follow_redirects=True`, **3.5 s sleep** between requests. All 15
     returned HTTP 200; no 403/429. Full fetch log in §11 (Appendix).
  5. Parsed each fetched page with the real `parse_page()` + `classify()`
     and recorded `page_type`, `warnings`, `n_links`, `n_sections`,
     `n_frames`.
- **What was NOT done:** no on-site search form was submitted (the form at
  `/bin/find_doc.php` was only fetched, not POSTed); no `robots.txt`
  re-fetch (already verified in SITE_AUDIT.md §2 — no content restrictions);
  no Google/Yandex `site:` search; no paginated following of the 44 region
  catalogs (only 1 non-REGIONS region was fetched, to test parser
  portability); the `mongol.html` 0-links anomaly was **not** structurally
  re-verified (fetch budget) — it is reported as a parser-output-verified
  gap with the root cause marked *Unknown — needs verification*.

---

## 2. Confirmed entry points

The site has **12 distinct entry-point classes**. The current `discover.py`
exposes 3 of them via CLI flags (`--home`, `--region`, `--letter`) and a
generic `--seed`. The other 9 are reachable only via `--seed` IF they pass
the `_is_doc_url` filter (see §9 — most do not).

| # | Entry point | URL (verified) | Discovered by `discover.py`? | Notes |
|---|-------------|----------------|------------------------------|-------|
| 1 | Homepage | `https://www.vostlit.info/` **[verified fixture `home.html`]** | ✅ `--home` flag | `#headmenu` has 28 letter links + "Документы"; `#main` has ~446 featured-doc links; footer has itogi + utility links. Two external search forms (Google `site:vostlit.info`, Yandex sitesearch) and 2 poll forms — these are not on-site search. |
| 2 | Documents hub | `/Texts/Dokumenty/index.phtml?id=2070` **[verified fixture `dokumenty_hub.html`]** | ❌ not seeded; reachable via `--seed` | Lists 44 region catalogs (see §3) + utility links (Карты, Указатели, Прочее, Поиск, Реперторий, MGH, MPH, Старые книги, etc.). `discover._is_catalog_or_index` recognises it, so `--seed <url>` would harvest its region links — but the user must know the URL. |
| 3 | Alphabetical author index | `/haupt-Dateien/index-Dateien/<LETTER>.phtml?id=<NNNN>` (28 letters A..JA) **[verified fixture `alpha_index_G.html` + headmenu in `home.html`]** | ✅ `--letter` flag, `ALPHA_LETTERS`/`ALPHA_IDS` complete | All 28 letters confirmed in `#headmenu`. IDs 2041..2069 (2066 skipped — Э=2067). `alpha_index_G.html` has 733 links in `#main`. |
| 4 | Itogi yearly archive | `/common/itogi.phtml?id=101` **[verified fixture `itogi.html`]** | ❌ NOT reachable | 25 yearly links (itogi1.phtml?id=97 for 2001 … itogi25.phtml?id=12320 for 2025). Note: id=12320 is shared by itogi15..itogi25 — the `id` query param is **not** a stable identifier for itogi pages. `--seed` fails: `_is_doc_url` rejects `/common/` (no `/texts/`). |
| 5 | **On-site search form** | `/bin/find_doc.php` **[verified live, fetch #5]** | ❌ NOT reachable | HTTP 200, page_type=`unknown`, parser warning `unclassified page`. 0 links, 0 sections. This is a real on-site search endpoint (the homepage's "Поиск" link) that discover.py ignores entirely. |
| 6 | **Bibliographic indexes hub** | `/common/lib_uk.phtml?id=1741` **[verified live, fetch #10]** | ❌ NOT reachable | HTTP 200, title "БИБЛИОГРАФИЧЕСКИЕ УКАЗАТЕЛИ", page_type=`document_text` (misclassified). 29 sections, **0 links harvested** (the page IS an index but the parser treats it as a document). |
| 7 | **Misc tables hub** | `/common/tables.phtml?id=110` **[verified live, fetch #11]** | ❌ NOT reachable | HTTP 200, title "ПРОЧЕЕ", page_type=`document_text`. 9 sections, 1 link. |
| 8 | **Maps index** | `/common/karten.phtml?id=108` **[link verified in `home.html` + `dokumenty_hub.html`]** | ❌ NOT reachable | Image-gallery hub for the whole site. Not fetched (budget); structure assumed same as `karten.phtml?id=1906` fixture (image_gallery). `_is_doc_url` rejects `/common/`. |
| 9 | **Repertorium (European medieval texts)** | `https://vostlit.info/Repertorium/index.htm` **[verified live, fetch #15]** | ❌ NOT reachable | HTTP 200, page_type=`collection_index`, title "Перечень текстов европейского Средневековья", **682 links** to `/Repertorium/<author>/<work>.htm`. A whole parallel catalog. `--seed` would harvest it (passes `_is_catalog_or_index` because path ends `/index.htm`), but every child link is rejected by `_is_doc_url` (no `/texts/`). |
| 10 | **MGH contents** | `https://vostlit.info/MGH/index.htm` **[link verified in `home.html`]** | ❌ NOT reachable | Monumenta Germaniae Historica contents index. Not fetched (budget); same `/MGH/` path issue as Repertorium. |
| 11 | **MPH contents** | `https://vostlit.info/MPH/index.htm` **[link verified in `home.html`]** | ❌ NOT reachable | MPH contents index. Not fetched; same issue. |
| 12 | **Utility pages** | `/common/help.phtml?id=235`, `/common/about.phtml?id=658`, `/common/uslov_obozn.phtml?id=658` (abbreviations), `/common/helfer.phtml?id=658` **[links verified in `home.html`]** | ❌ NOT reachable | Help / about / abbreviations / helpers pages. Not fetched. `_is_doc_url` rejects all. |

**Summary:** of 12 entry-point classes, **3 are wired into the CLI** (home,
region, letter), **1 is partially reachable** via `--seed` (documents hub),
and **8 are completely unreachable** through the standard discovery
pipeline (itogi, on-site search, bibliographic indexes, misc tables, maps
index, Repertorium, MGH, MPH, utility pages).

---

## 3. Regional catalog completeness

The documents hub (`/Texts/Dokumenty/index.phtml?id=2070`, fixture
`dokumenty_hub.html`) lists **44 region catalogs** — verified by two
independent counts over the fixture (all `<a>` whose href is a bare
relative `.htm`/`.html` filename). The earlier SITE_AUDIT.md §4.1 reported
"45 region links" — that count appears to have included the "Карты" entry
(which points to `/common/karten.phtml?id=108`, **not** a region). The
honest count is **44**.

`discover.REGIONS` defines 9 friendly-name keys mapping to **5** actual
region files: `kavkaz.html`, `russ.htm`, `krym.html`, `m.asien.htm`,
`turk.htm`. The remaining **39 of 44 region files (88.6%) have no friendly
slug**.

**Important mitigation:** `discover()` has a fallback
(`slug = REGIONS.get(r.lower(), r if r.endswith((".html", ".htm")) else r + ".html")`)
so a user CAN pass `--region mongol.html` and it will fetch
`/Texts/Dokumenty/mongol.html`. So the gap is in **usability** (no friendly
names, `regions` CLI command lists only 5) rather than raw capability —
**provided the parser can actually harvest the catalog** (see the mongol
caveat below).

| # | Region label (ru) | Slug (filename) | In `REGIONS`? | n_docs in catalog |
|---|--------------------|-----------------|---------------|-------------------|
| 1 | АВСТРИЯ | `austria.html` | ❌ | *Unknown — needs verification* |
| 2 | АЛБАНИЯ | `albanien.html` | ❌ | *Unknown* |
| 3 | АНГЛИЯ | `engl.html` | ❌ | *Unknown* |
| 4 | АРАВИЯ | `aravien.html` | ❌ | *Unknown* |
| 5 | АФРИКА | `afrika.html` | ❌ | *Unknown* |
| 6 | БОЛГАРИЯ | `bulgarien.html` | ❌ | *Unknown* |
| 7 | ВЕНГРИЯ | `ungarn.html` | ❌ | *Unknown* |
| 8 | ВИЗАНТИЯ | `vizant.htm` | ❌ | *Unknown* |
| 9 | ГЕРМАНИЯ | `germany.html` | ❌ | *Unknown* |
| 10 | ГОЛЛАНДИЯ | `niederlande.html` | ❌ | *Unknown* |
| 11 | ЕГИПЕТ | `egipet.htm` | ❌ | *Unknown* |
| 12 | ЗОЛОТАЯ ОРДА | `zolotoord.html` | ❌ | *Unknown* |
| 13 | ИНДИЯ | `indien.html` | ❌ | *Unknown* |
| 14 | ИРАН | `persien.html` | ❌ | *Unknown* |
| 15 | ИРЛАНДИЯ | `irland.html` | ❌ | *Unknown* |
| 16 | ИСПАНИЯ | `spain.htm` | ❌ | *Unknown* |
| 17 | ИТАЛИЯ | `italy.html` | ❌ | *Unknown* |
| 18 | **КАВКАЗ** | `kavkaz.html` | ✅ (3 keys: caucasus/kavkaz/кавказ) | ~349 rows in 2 tables (table 0: 64 rows; table 1: 285 rows) **[verified fixture, partial fragment — full page is 750 KB]** |
| 19 | КИТАЙ | `china.htm` | ❌ | *Unknown* |
| 20 | КОРЕЯ | `korea.html` | ❌ | *Unknown* |
| 21 | КРЕСТОВЫЕ ПОХОДЫ | `kreuzzug.html` | ❌ | *Unknown* |
| 22 | **КРЫМ** | `krym.html` | ✅ (2 keys: crimea/krym) | *Unknown* |
| 23 | ЛИВОНИЯ | `livonia.html` | ❌ | *Unknown* |
| 24 | ЛИТВА | `litva.html` | ❌ | *Unknown* |
| 25 | **МОНГОЛИЯ** | `mongol.html` | ❌ | **0 links harvested** **[verified live, fetch #1]** — parser yielded `region_catalog` + 1 heading section + 0 document links. Root cause *Unknown — needs structural verification* (likely a non-`<td><a>` layout). |
| 26 | ОРДЕНА | `ordena.html` | ❌ | *Unknown* |
| 27 | ПОЛЬША | `polen.html` | ❌ | *Unknown* |
| 28 | ПОРТУГАЛИЯ | `portugal.html` | ❌ | *Unknown* |
| 29 | ПУТЕШЕСТВИЯ | `reisen.html` | ❌ | *Unknown* |
| 30 | **РОССИЯ** | `russ.htm` | ✅ (2 keys: russia/russ) | *Unknown* |
| 31 | РУМЫНИЯ И МОЛДАВИЯ | `rumaenien.html` | ❌ | *Unknown* |
| 32 | C. АМЕРИКА | `s_america.html` | ❌ | *Unknown* |
| 33 | CЕРБИЯ, МАКЕДОНИЯ, ЧЕРНОГОРИЯ, БОСНИЯ И ГЕРЦЕГОВИНА | `serb.html` | ❌ | *Unknown* |
| 34 | СКАНДИНАВИЯ | `skandinav.html` | ❌ | *Unknown* |
| 35 | **СРЕДНЯЯ АЗИЯ** | `m.asien.htm` | ✅ (1 key: middle_asia) | *Unknown* |
| 36 | **TУРЦИЯ** | `turk.htm` | ✅ (1 key: turkestan) | *Unknown* |
| 37 | УКРАИНА | `ukraine.htm` | ❌ | *Unknown* |
| 38 | ФРАНЦИЯ | `france.htm` | ❌ | *Unknown* |
| 39 | ХОРВАТИЯ | `kroat.html` | ❌ | *Unknown* |
| 40 | ЧЕХИЯ | `tschechien.html` | ❌ | *Unknown* |
| 41 | ШОТЛАНДИЯ | `scotl.html` | ❌ | *Unknown* |
| 42 | ЭФИОПИЯ | `aethiopien.html` | ❌ | *Unknown* |
| 43 | Ю.-В. АЗИЯ | `suedostasien.html` | ❌ | *Unknown* |
| 44 | ЯПОНИЯ | `japan.html` | ❌ | *Unknown* |

**Honest disclosure:** only 2 of 44 region catalogs have a verified
document count (kavkaz ~349 rows; mongol 0 links — anomalous). The other
42 are listed by URL but their document counts are *Unknown — needs
verification*. The audit did not fetch them (budget: 15 pages total).

**Two distinct gaps:**
1. **REGIONS map covers 5/44 files (11.4%)** by friendly name. The
   `regions` CLI command lists only these 5, so users have no programmatic
   way to discover the other 39 slugs. **Recommendation:** auto-populate
   `REGIONS` by harvesting the documents hub at startup (the hub is a
   single 15 KB page), OR add a `regions-from-hub` subcommand.
2. **Parser fragility across region layouts.** The `_parse_region_catalog`
   parser assumes the kavkaz.html structure (`<table><tr><td><a>`).
   `mongol.html` (54 KB, fetched) yielded 0 document links — suggesting
   at least one region uses a different layout. **Recommendation:** fetch
   3–5 more region catalogs and either generalise the parser (try `<td><a>`
   first, fall back to `<li><a>` / `<p><a>`) or document which regions are
   kavkaz-compatible.

---

## 4. Collection indexes found

A "collection index" is an `index.htm` page that lists sub-works of a
multi-part collection. The parser classifies these as `collection_index`
(in `fetch_page_types`, so they ARE fetched and parsed).

| Collection index | URL | Verified? | n_links harvested | Notes |
|------------------|-----|-----------|-------------------|-------|
| Dag_chron (13 Dagestan chronicles) | `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/index.htm` | ✅ fixture | 13 sub-work links (Derbend-name, Akhty-name, Tarikh-i Dagestan, etc.) | Parser handles ✓. `p.collection` set to title. |
| **AKAK Tom_1** (Акты Кавказской Археографической Комиссии, vol. 1) | `/Texts/Dokumenty/Kavkaz/AKAK/Tom_1/index.htm` | ✅ live fetch #7 | **1216 part-links** (pred.htm + Theil_I/1.htm … Theil_I/N.htm) | 226 KB. Parser handles ✓. Multi-volume collection (Tom_1, Tom_6_I, Tom_6_II confirmed in kavkaz fixture; Tom_2..Tom_12 assumed but not verified). |
| AKAK Tom_6_I | `/Texts/Dokumenty/Kavkaz/AKAK/Tom_6_I/index.htm` | link in kavkaz fixture | *Unknown* | Not fetched. |
| AKAK Tom_6_II | `/Texts/Dokumenty/Kavkaz/AKAK/Tom_6_II/index.htm` | link in kavkaz fixture | *Unknown* | Not fetched. |
| **32 collection indexes** in the kavkaz fragment alone | various `/Texts/Dokumenty/Kavkaz/.../index.htm` | links verified in `kavkaz_catalog.fragment.html` | *Unknown* | Includes Pers_dok_matenadaran_I/II/III, Russ_Kab_otn_1/2, Russ_Chech_otn, Arm_russ_otn_18v_II_I/II/III, Butkov_P_G_I, Feod_otn_Dagestan, Turk_pism_Dagestan, etc. Not individually fetched. |
| **Repertorium** (European medieval texts) | `https://vostlit.info/Repertorium/index.htm` | ✅ live fetch #15 | **682 links** to `/Repertorium/<author>/<work>.htm` | 78 KB. Parser classifies as `collection_index` ✓. **BUT** none of the 682 child links pass `_is_doc_url` (no `/texts/`), so `discover()` drops them all. See §9. |
| MGH contents | `https://vostlit.info/MGH/index.htm` | link in `home.html` | *Unknown* | Not fetched. Same `/MGH/` path issue. |
| MPH contents | `https://vostlit.info/MPH/index.htm` | link in `home.html` | *Unknown* | Not fetched. Same issue. |

**Gap — collection membership not recorded.** The `_parse_collection_index`
parser sets `p.collection = p.title` (the collection's own title) and
harvests part-links, but:
- The part-links are recorded with `kind="part"` but **no parent_collection_url** metadata.
- `crawl.py` does **not** auto-follow collection_index part-links (only frameset inner frames are auto-followed, see `crawl.py:148-160`). So a `collection_index` page is fetched and stored, but its 1216 (AKAK) or 682 (Repertorium) child documents are NOT enqueued for fetching — they're only discovered if the user re-runs `crawl --seed <collection_index_url>` AND the children pass `_is_doc_url`.

**Recommendation:** (a) auto-follow `collection_index` part-links in `crawl.py` (analogous to the frameset follow-through), recording `source_metadata.parent_collection_url`; (b) widen `_is_doc_url` to accept `/Repertorium/`, `/MGH/`, `/MPH/` paths so the parallel catalogs become crawlable.

---

## 5. Frameset variants confirmed

The frameset parser (`v0.2.0`, `_parse_frameset` + `_infer_frame_role`)
was verified on **3 frame\* variants fetched live** + **50+ variants
observed as link patterns** in the `alpha_index_G.html` fixture.

| Frame variant | Fetched URL | Verified? | n_frames | Inner frames (role inference) | Parser result |
|---------------|-------------|-----------|----------|-------------------------------|---------------|
| `framevved*.htm` | (Nogmov `framevved1.htm`, SITE_AUDIT v0.2.0) | ✅ prior | 2 | Hauptframe=main, Fussnoten=notes | ✓ works |
| `frametext*.htm` | (Gazavat-name, SITE_AUDIT) | ✅ prior | 2 | text=main, primtext=notes | ✓ works |
| `framepred*.htm` | (Galonifontibus, SITE_AUDIT) | ✅ prior | 2 | pred=main, primpred=notes | ✓ works |
| **`frameposl*.htm`** (послание = epistle) | `/Texts/rus10/Meier/frameposl1.htm` | ✅ live fetch #6 | 2 | `posl1.phtml`=main, `primposl1.phtml`=notes | ✓ works. Title "ПОСЛЕСЛОВИЕ. ЧАСТЬ 1". |
| **`framepril*.htm`** (приложение = appendix) | `/Texts/rus/Gvibert_2/framepril.htm` | ✅ live fetch #14 | 2 | `pril.phtml`=main, `primpril.phtml`=notes | ✓ works. Title "ГВИБЕРТ НОЖАНСКИЙ. О СВОЕЙ ЖИЗНИ. ПРИЛОЖЕНИЕ". |

**Additional frame\* prefixes observed as link patterns in
`alpha_index_G.html` (NOT fetched, but URL patterns verified):**
`framegel1..5`, `framekrinitsa`, `framevita`, `framekor`, `frametrakt`,
`framezametka_1859`, `framezametka_2018`, `frame1text`, `frametext_1`,
`framedrug_autor_1/2`, `framepredisl`, `framepredperev`, `frameprod1`,
`framepril1/2`, `framepred3`, `frametext91/92` (sub-numbering).

**Parser behaviour on all frame\* variants:** `classify()` returns
`frameset` for any page with a `<frameset>` tag (checked before the
bare-.htm branch). `_infer_frame_role` defaults to `"main"` for any frame
whose name doesn't match `fuss/note/prim` or `nav/menu/inhalt/left`. This
is **correct** for all observed variants (the main text frame is always
the non-`prim` one) but loses the semantic distinction (poslanie vs
prilozhenie vs predislovie). **Minor gap, not a coverage gap.**

**Conclusion:** the frameset parser is robust across all observed
variants. No coverage gap here.

---

## 6. Page types: skipped vs. fetchable

`config.fetch_page_types = (document_text, document_excerpt, notes_page,
image_gallery, collection_index, frameset)`. The crawler (`crawl.py:123`)
sets `status='skipped'` for any page whose `page_type` is NOT in this
tuple. The classifier (`parser.classify`) produces these types:

| `classify()` output | In `fetch_page_types`? | Fetched? | Useful text in page? | Recommendation |
|----------------------|------------------------|----------|----------------------|----------------|
| `home` | ❌ | skipped | ~446 featured-doc link labels (author/work titles) | Keep skipped — navigation only. |
| `alpha_index` | ❌ | skipped | **YES** — 710+ entries, each `<p>` has CAPS author header + work titles + part-link labels. Rich metadata. | **FETCH** (or at minimum index `p.extracted_text`). Currently the seed script force-inserts it as `parsed`, but the real crawler would skip it. |
| `documents_hub` | ❌ | skipped | 44 region labels + utility labels | Keep skipped — navigation. |
| `region_catalog` | ❌ | skipped | **YES** — kavkaz.html has 349 `<td>` cells, each with a document title + date + part-link labels. Currently NOT indexed. | **FETCH** — the `<td>` text is exactly the document-description metadata the research engine needs. |
| `itogi_index` | ❌ | skipped | **YES** — each yearly page lists newly-posted documents with titles + links. | **FETCH** — provides a chronological-discovery path. |
| `document_text` | ✅ | fetched | (the doc itself) | ✓ |
| `document_excerpt` | ✅ | — | — | **DEAD TYPE.** `classify()` never returns `document_excerpt`. `otryv*.phtml` pages are classified as `document_text`. Either remove from `fetch_page_types` or make `classify()` return it for `otryv`/`otr` paths. |
| `notes_page` | ✅ | fetched | ✓ | ✓ |
| `image_gallery` | ✅ | fetched | ✓ | ✓ |
| `collection_index` | ✅ | fetched | ✓ (but children not auto-followed — see §4) | ✓ |
| `frameset` | ✅ | fetched + inner frames auto-followed | ✓ | ✓ |
| `unknown` | ❌ | skipped | varies | The `/bin/find_doc.php` search form lands here. See §7. |

**Three concrete text-loss gaps:**
1. **`region_catalog` text is not indexed.** kavkaz.html's 349 `<td>` cells
   contain document descriptions (title, date, edition) that the research
   engine could use for source-evaluation. The parser DOES extract them
   into `p.extracted_text` and `p.links`, but the crawler skips the page
   type entirely, so nothing is stored. **Fix:** add `region_catalog` to
   `fetch_page_types` (the parser already handles it).
2. **`alpha_index` text is not indexed** by the real crawler (only by the
   seed script bypass). Same fix.
3. **`itogi_index` is not indexed** and not even reachable (see §2 #4).

---

## 7. Unknown / unparseable page examples

Pages that `classify()` cannot assign a meaningful type, or that the
parser misclassifies with content loss:

| Page | URL (verified) | `classify()` result | Parser warning | Real content loss? |
|------|----------------|----------------------|----------------|--------------------|
| **On-site search form** | `/bin/find_doc.php` **[live #5]** | `unknown` | `unclassified page: https://www.vostlit.info/bin/find_doc.php` | The page is a search form (6.6 KB). Parser yields 0 sections, 0 links. The form's `action` and input fields are not inspected. **Recommendation:** add a `search_form` page type, OR at minimum record the form's existence so a future feature can submit queries. |
| **Chronology page** | `/Texts/rus14/Tegan/chrono.phtml?id=1472` **[live #4]** | `document_text` (misclassified) | `no #dann citation block found` | **YES — 0 sections extracted!** The page is a chronology table (`<table>` of dates/events). The `.phtml` parser skips all `<p>` inside `<table>` (`parser.py:412` `if el.find_parent(["table"]): continue`), and the chronology is entirely table-based. **Fix:** add a `chrono` page type (detect `chrono` in path) with a table-aware parser, OR relax the `.phtml` parser to emit `<tr><td>` rows as sections when the page is a chronology. |
| **Glossary page** | `/Texts/rus10/Meier/glossar.phtml?id=294` **[live #2]** | `document_text` (misclassified) | `no #dann citation block found` | Partial — 134 sections extracted (the glossary entries are `<p>`s, so they're captured), but no `#dann` citation. Title "УКАЗАТЕЛИ". **Minor gap** — content is captured but mislabelled. |
| **Abbreviations page** | `/Texts/Dokumenty/Polen/X/980-1000/Dagome_iudex/sokr.phtml?id=7919` **[live #3]** | `document_text` (misclassified) | `no #dann citation block found` | Partial — 35 sections extracted. Title "СОКРАЩЕНИЯ". Same as glossary. |
| **Bibliographic indexes hub** | `/common/lib_uk.phtml?id=1741` **[live #10]** | `document_text` (misclassified) | `no #dann citation block found` | **YES — 0 links harvested.** The page IS an index (title "БИБЛИОГРАФИЧЕСКИЕ УКАЗАТЕЛИ") but the `.phtml` parser doesn't harvest `<a>` links from `#main` (only `primtext` and `/Texts/` links, and this page's links go elsewhere). **Fix:** add an `index_hub` page type that harvests all `#main` links. |
| **Misc tables hub** | `/common/tables.phtml?id=110` **[live #11]** | `document_text` (misclassified) | `no #dann citation block found` | Partial — 9 sections, 1 link. Title "ПРОЧЕЕ". |
| **Edition page** | `/Texts/rus10/Meier/izd.phtml?id=11579` **[live #9]** | `document_text` | (none) | ✓ works — 13 sections, title "ОТ ИЗДАТЕЛЯ". No issue. |
| **Overview/review (bare .htm)** | `/Texts/rus8/Gandzakeci_2/obzor1.htm` **[live #8]** | `document_text` (bare .htm branch) | `bare .htm document (no site chrome)` | ✓ works — 43 sections, title "-". No issue. |
| **Excerpt** | `/Texts/rus7/Gardizi/otryv1.phtml?id=1507` **[live #12]** | `document_text` | (none) | ✓ works — 50 sections. (Confirms `document_excerpt` type is dead — see §6.) |
| **Introduction** | `/Texts/rus12/Bav_geogr/vved2.phtml?id=9695` **[live #13]** | `document_text` | (none) | ✓ works — 22 sections, title "ВВЕДЕНИЕ". |

**Two real content-loss bugs:**
1. **`chrono.phtml` → 0 sections.** The `.phtml` parser's table-skip rule
   drops all chronology content. **Recommendation:** add a `chrono` page
   type (detect `chrono` in path) with a table-row-aware parser.
2. **`lib_uk.phtml` → 0 links.** The bibliographic-indexes hub is
   misclassified as `document_text` and its index links are not harvested.
   **Recommendation:** add an `index_hub` page type for `/common/lib_uk`,
   `/common/tables`, and similar hubs.

---

## 8. Coverage metrics from the DB (real numbers)

Queried `data/vostlit.db` (3.0 MB, 2025-10-27):

```
=== documents.status ===
parsed          10

=== documents.page_type ===
document_text        5
alpha_index          1
collection_index     1
image_gallery        1
notes_page           1
region_catalog       1

=== crawl_log ===
(empty — 0 rows)

=== totals ===
documents           10
crawl_log            0
document_sections  661
document_versions   10
entities             5
name_variants        4
mentions             0
research_notes       0
```

**Interpretation — honest:**

| Metric | Value | What it means |
|--------|-------|----------------|
| Documents discovered via `discover()` pipeline | **0** | `crawl_log` is empty — `discover()` has never been run end-to-end against the persistent DB. |
| Documents fetched+parsed via `crawl` pipeline | **0** | Same — no `crawl_log` rows, no `discovered`/`skipped`/`error` statuses. |
| Documents force-imported by `scripts/seed_corpus.py` | **10** | All 10 docs were inserted directly via `store.upsert_document`, bypassing `discover()` + `crawl()`. All have `status='parsed'`. |
| Documents skipped (page_type not in `fetch_page_types`) | **0** | The seed script imports `alpha_index` + `region_catalog` (both NOT in `fetch_page_types`) as `parsed` — the real crawler would have skipped them. |
| Documents errored | **0** | — |
| Real coverage of the discover→crawl pipeline | **UNTESTED** | The worklog (Task main-final) mentions "LIVE verification: crawl --region caucasus --limit 2 fetched 2 real pages", but those records are NOT in the persistent DB — likely the live test used a `tmp_path` DB (see `tests/test_integration_live.py:37` `cfg.db_path = tmp_path / "live.db"`). |

**The bottom line:** the discover→crawl→fetch→parse pipeline has **never
been exercised end-to-end against the persistent DB**. The 10 documents in
`data/vostlit.db` are all fixture imports. Every coverage claim about the
real site is therefore based on the 15 live fetches in this audit + the 15
fetches in SITE_AUDIT.md, NOT on pipeline behaviour.

---

## 9. URL patterns the discoverer misses

`discover._is_doc_url(url)` requires:
```python
"/texts/" in path.lower()  AND  path.endswith((".phtml", ".htm", ".html"))
```

This filter **silently drops** the following URL classes (verified):

| URL class | Example (verified) | Dropped? | Impact |
|-----------|---------------------|----------|--------|
| `/common/*.phtml` | `/common/itogi.phtml?id=101`, `/common/lib_uk.phtml?id=1741`, `/common/tables.phtml?id=110`, `/common/karten.phtml?id=108` | ✅ dropped (no `/texts/`) | All 5 utility-hub entry points unreachable. |
| `/bin/*.php` | `/bin/find_doc.php` | ✅ dropped (no `/texts/`, not `.phtml`/`.htm`) | On-site search form unreachable. |
| `/Repertorium/*.htm` | `https://vostlit.info/Repertorium/Am/abbo_sangermanensis.htm` | ✅ dropped (no `/texts/`) | All 682 Repertorium documents unreachable. |
| `/MGH/*.htm` | `https://vostlit.info/MGH/...` | ✅ dropped | MGH catalog unreachable. |
| `/MPH/*.htm` | `https://vostlit.info/MPH/...` | ✅ dropped | MPH catalog unreachable. |
| `../../Texts/...` relative | `../../Texts/rus16/Gayling/text.phtml?id=4038` (from alpha index) | ❌ handled correctly by `urljoin()` | ✓ |
| Links with spaces | (none found in `alpha_index_G.html`) | n/a | No issue observed. |
| Non-id query params | `itogi15.phtml?id=12320` … `itogi25.phtml?id=12320` (shared id) | partial — `stable_id_from_url` uses the full canonical URL (path differs), so stable_ids differ. But the `id` query param alone is **not** unique for itogi pages. | Documented in §2 #4. |

**Additional filter issue — `_is_catalog_or_index`:**
This function (used to decide whether to `harvest()` a `--seed` URL) recognises:
`/`, `/haupt-dateien/index-dateien/`, `/texts/dokumenty/index.phtml`,
`*/index.htm`, `/texts/dokumenty/*.html?`. It does **NOT** recognise:
- `/common/itogi.phtml` (itogi hub) — so `--seed <itogi_url>` calls `add()`
  directly, which drops it via `_is_doc_url`.
- `/bin/find_doc.php` (search form).
- `/Repertorium/index.htm` IS recognised (ends `/index.htm`), so it would
  be harvested — but its 682 children are then dropped by `_is_doc_url`.

**Recommendation:** widen `_is_doc_url` to accept `/Repertorium/`,
`/MGH/`, `/MPH/`, and `/common/` paths (or make the filter configurable).
Widen `_is_catalog_or_index` to recognise `/common/itogi.phtml` and
`/common/lib_uk.phtml` as harvestable hubs.

---

## 10. Gaps & recommendations (concrete)

Ordered by coverage impact (highest first).

### P0 — content silently lost

1. **`chrono.phtml` pages yield 0 sections.** The `.phtml` parser skips
   all `<p>` inside `<table>` (`parser.py:412`), and chronologies are
   table-based. **Verified** on Tegan `chrono.phtml?id=1472` (fetch #4):
   0 sections, 28 KB page. **Fix:** add a `chrono` page type (detect
   `chrono` in path) with a `<tr><td>`-row-aware parser; emit each row as
   a `body` section. Also affects Schiltberger, Klavicho chronologies
   (links in `home.html`).

2. **`region_catalog` pages are skipped by the crawler** (not in
   `fetch_page_types`). kavkaz.html's 349 `<td>` cells contain document
   descriptions (title + date + part-link labels) that the research
   engine needs for source evaluation. **Fix:** add `region_catalog` to
   `config.fetch_page_types`. The parser already handles the page.

3. **`alpha_index` pages are skipped by the real crawler.** The 710+
   entries per letter contain author/work titles. **Fix:** add
   `alpha_index` to `fetch_page_types` (or at minimum index
   `p.extracted_text`).

4. **`lib_uk.phtml` (bibliographic indexes hub) yields 0 links.**
   Misclassified as `document_text`. **Fix:** add an `index_hub` page
   type for `/common/lib_uk`, `/common/tables`, and harvest all `#main`
   `<a>` links.

### P1 — entry points unreachable

5. **`/Repertorium/`, `/MGH/`, `/MPH/` parallel catalogs unreachable.**
   `_is_doc_url` rejects them (no `/texts/`). Repertorium alone has 682
   European-medieval documents (verified). **Fix:** widen `_is_doc_url`
   to accept these path prefixes (or make it configurable).

6. **`/common/itogi.phtml` (yearly archive) unreachable.** 25 yearly
   pages, each listing newly-posted documents. **Fix:** add an
   `--itogi` flag to `discover()` that harvests the itogi hub, then
   harvests each yearly page; widen `_is_doc_url` to accept `/common/`.

7. **`/bin/find_doc.php` (on-site search) unreachable.** **Fix:** add a
   `search_form` page type; record the form's existence in the DB so a
   future feature can submit queries (do NOT auto-submit — be polite).

8. **`/common/karten.phtml?id=108` (site-wide maps index) unreachable.**
   **Fix:** same as #6 — widen `_is_doc_url` for `/common/`.

### P1 — REGIONS map incomplete

9. **REGIONS covers 5/44 region files.** Add friendly slugs for the
   other 39, OR (better) auto-populate REGIONS by harvesting the
   documents hub at startup (15 KB page, 44 links). Also fix the
   `regions` CLI command to list all 44.

10. **`mongol.html` (non-REGIONS region) yielded 0 document links.**
    Parser assumes kavkaz-style `<td><a>` tables. **Fix:** fetch 3–5
    more region catalogs to verify the layout assumption; generalise
    `_parse_region_catalog` to fall back to `<li><a>` / `<p><a>` if no
    `<td><a>` found. **Root cause currently *Unknown — needs
    verification*.**

### P2 — collection membership & auto-follow

11. **`collection_index` children not auto-followed.** `crawl.py`
    auto-follows frameset inner frames but NOT collection_index
    part-links. AKAK Tom_1 has 1216 part-links; none would be enqueued.
    **Fix:** add a collection_index follow-through in `crawl.py`
    (analogous to `_fetch_parse_store_inner`), recording
    `source_metadata.parent_collection_url`.

12. **`document_excerpt` page type is dead.** `classify()` never returns
    it; `otryv*.phtml` is classified as `document_text`. **Fix:** either
    remove `document_excerpt` from `fetch_page_types` or make
    `classify()` return it for `otryv`/`otr` paths (lower priority —
    content is still captured, just mislabelled).

### P2 — DB coverage untested

13. **The discover→crawl pipeline has never been run end-to-end against
    the persistent DB.** `crawl_log` is empty; all 10 docs are
    force-imported. **Fix:** run `python3 -m vostlit_research crawl
    --region caucasus --limit 10` against the real DB and verify that
    `crawl_log` rows are written and statuses transition
    `discovered`→`parsed`/`skipped`/`error`. This is a prerequisite for
    trusting any coverage claim about the live site.

### P3 — minor

14. **`_infer_frame_role` loses semantic distinctions** (poslanie vs
    prilozhenie vs predislovie). All map to `"main"`. Low priority —
    content is captured.

15. **`itogi` pages share `id=12320`** (itogi15..itogi25). The
    `stable_id_from_url` uses the full canonical URL so stable_ids
    differ, but the `id` query param is not unique. Document this in
    `SITE_AUDIT.md`.

---

## 11. Appendix — every URL fetched during this audit

15 live fetches, all HTTP 200, no 403/429. Raw log at
`/home/z/my-project/audit_fetch_log.json`.

| # | Label | URL | Status | Bytes | Content-Type | `classify()` | n_links | n_sections | n_frames | Warnings |
|---|-------|-----|--------|-------|--------------|--------------|---------|------------|----------|----------|
| 1 | region_mongol | `https://www.vostlit.info/Texts/Dokumenty/mongol.html` | 200 | 54173 | text/html; charset=WINDOWS-1251 | `region_catalog` | **0** | 1 | 0 | (none) |
| 2 | glossar_meier | `https://www.vostlit.info/Texts/rus10/Meier/glossar.phtml?id=294` | 200 | 30096 | text/html; charset=WINDOWS-1251 | `document_text` | 0 | 134 | 0 | `no #dann citation block found` |
| 3 | sokr_dagome | `https://www.vostlit.info/Texts/Dokumenty/Polen/X/980-1000/Dagome_iudex/sokr.phtml?id=7919` | 200 | 10269 | text/html; charset=WINDOWS-1251 | `document_text` | 0 | 35 | 0 | `no #dann citation block found` |
| 4 | chrono_tegan | `https://www.vostlit.info/Texts/rus14/Tegan/chrono.phtml?id=1472` | 200 | 28478 | text/html; charset=WINDOWS-1251 | `document_text` | 0 | **0** | 0 | `no #dann citation block found` |
| 5 | find_doc | `https://www.vostlit.info/bin/find_doc.php` | 200 | 6642 | text/html; charset=WINDOWS-1251 | `unknown` | 0 | 0 | 0 | `unclassified page: https://www.vostlit.info/bin/find_doc.php` |
| 6 | frameposl_meier | `https://www.vostlit.info/Texts/rus10/Meier/frameposl1.htm` | 200 | 944 | text/html; charset=WINDOWS-1251 | `frameset` | 2 | 2 | 2 | `frameset page: content is in inner frames; fetch them for full text` |
| 7 | akak_tom1_index | `https://www.vostlit.info/Texts/Dokumenty/Kavkaz/AKAK/Tom_1/index.htm` | 200 | 226506 | text/html; charset=WINDOWS-1251 | `collection_index` | **1216** | 0 | 0 | (none) |
| 8 | obzor_gandzakeci | `https://www.vostlit.info/Texts/rus8/Gandzakeci_2/obzor1.htm` | 200 | 12891 | text/html; charset=WINDOWS-1251 | `document_text` | 0 | 43 | 0 | `bare .htm document (no site chrome)` |
| 9 | izd_meier | `https://www.vostlit.info/Texts/rus10/Meier/izd.phtml?id=11579` | 200 | 11934 | text/html; charset=WINDOWS-1251 | `document_text` | 0 | 13 | 0 | (none) |
| 10 | lib_uk | `https://www.vostlit.info/common/lib_uk.phtml?id=1741` | 200 | 12729 | text/html; charset=WINDOWS-1251 | `document_text` | **0** | 29 | 0 | `no #dann citation block found` |
| 11 | tables_misc | `https://www.vostlit.info/common/tables.phtml?id=110` | 200 | 8324 | text/html; charset=WINDOWS-1251 | `document_text` | 1 | 9 | 0 | `no #dann citation block found` |
| 12 | otryv_gardizi | `https://www.vostlit.info/Texts/rus7/Gardizi/otryv1.phtml?id=1507` | 200 | 33518 | text/html; charset=WINDOWS-1251 | `document_text` | 0 | 50 | 0 | (none) |
| 13 | vved_bav_geogr | `https://www.vostlit.info/Texts/rus12/Bav_geogr/vved2.phtml?id=9695` | 200 | 16099 | text/html; charset=WINDOWS-1251 | `document_text` | 0 | 22 | 0 | (none) |
| 14 | framepril_gvibert | `https://www.vostlit.info/Texts/rus/Gvibert_2/framepril.htm` | 200 | 942 | text/html; charset=WINDOWS-1251 | `frameset` | 2 | 2 | 2 | `frameset page: content is in inner frames; fetch them for full text` |
| 15 | repertorium | `https://vostlit.info/Repertorium/index.htm` | 200 | 77793 | text/html; charset=WINDOWS-1251 | `collection_index` | **682** | 0 | 0 | (none) |

**Total: 15 fetches, 15 × HTTP 200, 0 × 403/429, 0 errors.** No access
control was bypassed. Polite delay (3.5 s) was maintained between all
requests. UA was `Mozilla/5.0 (compatible; vostlit-research-audit/0.1)`.

**Pages re-used from existing fixtures (not re-fetched):**
`home.html`, `alpha_index_G.html`, `dokumenty_hub.html`, `itogi.html`,
`kavkaz_catalog.fragment.html`, `document_text_dag_chron_index.html`,
and the 7 other document-text/notes/image fixtures — see
`tests/fixtures/fixtures_manifest.json` for sha256 + source URLs.

---

*End of SITE_COVERAGE_AUDIT.md. Generated by Subagent A (site-archaeologist),
Task ID `A-site`, 2025-10-27.*
