# SITE_AUDIT.md — Structural audit of https://www.vostlit.info/

> A factual, evidence-based audit of the real HTML structure of
> `https://www.vostlit.info/`, written so that a parser can be coded against
> **verified** selectors rather than guesses.
>
> Every selector, URL pattern, and structural claim below was checked against a
> page that was actually fetched during this audit (see the Appendix for the full
> fetch log). Where something is **not** known it is marked
> *Unknown — needs verification*.

---

## 1. Audit method & date

- **Date:** 2025-10-27 (Europe/Moscow, UTC+3).
- **Method:** 15 distinct pages were fetched with `httpx` 0.28.1, using
  `User-Agent: Mozilla/5.0 (compatible; vostlit-research-audit/0.1)`,
  `timeout=30 s`, `follow_redirects=True`, and a **3–4 s sleep** between
  requests. Each response was decoded with Python's `'windows-1251'` codec
  (per the server's `Content-Type` header) and then parsed with
  `BeautifulSoup(..., "lxml")`. Raw bytes and decoded text were saved for
  offline analysis; 13 of them were then copied as test fixtures (see §14 and
  `tests/fixtures/`).
- **Scope:** homepage, the alphabetical index for one letter (Г), the
  documents hub, the "итоги прошлых лет" index, the **Caucasus regional
  catalog** (`kavkaz.html`, 750 KB), six document-text pages (five `.phtml`
  and one `.htm`), the Dagestan-chronicles collection index, and one
  notes ("Комментарии") page.
- **What was NOT done:** no on-site search form was used (none was found —
  see §2); no Google `site:` search was performed; no `frameset`-style pages
  were followed into their frames (the frameset `frame*.htm` URLs are noted
  but their inner content was not fetched, to keep the fetch count modest).

---

## 2. Environment & access notes

### 2.1 robots.txt (verified — `https://www.vostlit.info/robots.txt`, HTTP 200)

```
User-agent: *
Allow: /*.css
Allow: /*.js
Allow: /wp-content/cache/*.css
Allow: /wp-content/cache/*.js
Allow: /wp-includes/*.css
Allow: /wp-includes/*.js
Disallow: /wp-admin
Disallow: /wp-includes
Disallow: /wp-content/plugins
Disallow: /wp-content/cache
Disallow: /wp-json/

User-agent: Yandex
[same Allow/Disallow rules]
Host: https://www.vostlit.info
```

Notes:
- The robots.txt is a **WordPress-style** file (mentions `wp-admin`,
  `wp-includes`, `wp-json`) — almost certainly a leftover/copy-paste; the
  actual site is **PHP/5.6.40 on nginx/1.30.2** (per HTTP headers) with no
  WordPress visible in the URLs we fetched. The `Disallow` rules therefore do
  not restrict any of the actual content paths (`/haupt-Dateien/`,
  `/Texts/`, `/common/`).
- There is **no** `Crawl-delay` directive.
- No specific `Disallow` targets any content path. The collector should still
  self-throttle (the audit used 3–4 s between requests with no push-back).

### 2.2 Server / HTTP behaviour (verified)

- `Server: nginx/1.30.2`; `X-Powered-By: PHP/5.6.40` (homepage header).
- All HTML pages return `Content-Type: text/html; charset=WINDOWS-1251`.
  The charset is declared in BOTH the HTTP header and an in-document
  `<META http-equiv=Content-Type content="text/html; charset=windows-1251">`.
- 404 pages come from **Apache/2.4.58 (Ubuntu)** (`Server` header on the 404
  response) — there is an Apache backend behind the nginx frontend. The 404
  body is a default Apache 404 page (`<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">`).
  This means a missing `.phtml`/`.htm` file returns **404**, not a soft
  "document not found" page.
- **No 403 / 429 / redirects observed** on any of the 15 fetches. One 404
  was deliberately provoked (`/Texts/rus13/Sirvan_Derbend/text1.phtml?id=1906`)
  to confirm that the `id` query parameter is **per-page**, not per-work: the
  `karten.phtml?id=1906` page exists, but `text1.phtml?id=1906` does not —
  i.e. each `.phtml` file has its own `id`.
- **No JS-only content** detected: every page is fully renderable server-side
  and parseable with BeautifulSoup. No `<script>`-rendered text was found.
- No anti-bot challenge (no Cloudflare interstitial, no captcha).

### 2.3 On-site search (verified absent)

The homepage `#headmenu` contains only the А..Я letter links + "Документы".
The `#leftmenu` / `#rightmenu` blocks contain site chrome ("Каталоги",
"Карты", "Указатели", "Форум", "Гостевая", "Реперторий", etc.) but **no
`<form>` / search box**. There is no `?q=` or `?search=` URL pattern.
**Discovery must be done by crawling** the alphabetical index, the documents
hub, and the regional catalogs.

---

## 3. Encoding & orthography (verified)

- **Encoding:** `windows-1251` (Cyrillic legacy) on every one of the 15 pages
  fetched, including `.htm` files served from `/Texts/Dokumenty/Kavkaz/...`.
  No page differed. The decoder MUST be `'windows-1251'` (explicit), not
  BeautifulSoup auto-detection.
- **Orthography:** all sampled texts use **modern Russian orthography**. A
  character-count scan for pre-reform letters (`ѣ ѳ ѵ і ѫ ѧ`) returned **0**
  for every page (including the 18th-c. translations of Tunmann, the
  6th-c. Iordan, and the 18th-c. Dagestan doc). The site publishes modern
  scholarly translations/editions, not facsimiles of pre-reform originals.
  *Unknown — needs verification:* whether any pre-reform-text page exists on
  the site (it might, for old-Russian primary sources), but none was found in
  the sample.
- The site mixes Cyrillic with substantial **Latin** text (original-language
  titles like `DER KRIMISCHE STAAT`, Latin quotes in Iordan's commentaries,
  `Monumenta German. Historica` in side menus). Both windows-1251 and the
  Python decoder handle this fine.

---

## 4. URL structure & stable identifiers

### 4.1 URL families (all verified by fetching at least one member)

| Family | URL pattern | Example (verified) | Notes |
|---|---|---|---|
| Homepage | `/` | `https://www.vostlit.info/` | Full site chrome, `#main` holds featured docs. |
| Alphabetical index | `/haupt-Dateien/index-Dateien/<LETTER>.phtml?id=<NNNN>` | `…/G.phtml?id=2044` | Letters A..JA, ids 2041..2069. **One page per Cyrillic letter**; lists works (not just authors). |
| Documents hub | `/Texts/Dokumenty/index.phtml?id=2070` | (verified) | Regional catalog index — 45 regions, each linking to a `<region>.html` page. |
| Regional catalog (HTML) | `/Texts/Dokumenty/<region>.html` | `…/Dokumenty/kavkaz.html` (verified, 750 KB) | Plain `.html`, **no `id`**, **no site chrome**, just a big table of documents. Other verified-by-listing examples: `russ.htm`, `krym.html`, `m.asien.htm`, `turk.htm`, etc. |
| Document text (`.phtml`) | `/Texts/rus<N>/<Author_slug>/<file>.phtml?id=<NNNN>` | `…/rus/Iordan/text2.phtml?id=577` | Full chrome. `<file>` ∈ `text1..N.phtml`, `otryv1..N.phtml`, `pred.phtml`, `pred2.phtml`, `primtext1..N.phtml` (notes), `karten.phtml` (maps), `lit.phtml` (literature), `sokr.phtml` (abbreviations), `izd.phtml` (изд.), `avtor.phtml`, `glossar.phtml`, `zakl.phtml`, `chrono.phtml`, `recenz_*.phtml`, etc. |
| Document text (`.htm`, "bare") | `/Texts/Dokumenty/<region>/<century>/<period>/<slug>/<file>.htm` | `…/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm` | **No site chrome**, no `#main`, no `id`. Files like `text.htm`, `text1.htm`, `frametext1.htm`, `pred.htm`, `index.htm`, `karten.htm`. |
| Collection index (`.htm`) | `/Texts/Dokumenty/<region>/<century>/<period>/<slug>/index.htm` | `…/Kavkaz/VI/Dag_chron/index.htm` | Lists the sub-works of a multi-part collection (e.g. the 13 Dagestan chronicles). |
| Notes page | `/Texts/rus<N>/<Author_slug>/primtext<M>.phtml` (no `id`!) | `…/rus/Iordan/primtext6.phtml` | Verified: HTTP 200, **no `id` query needed**. Holds notes 401–500 for Iordan. |
| "Итоги прошлых лет" index | `/common/itogi.phtml?id=101` | (verified) | Lists 25 yearly links `itogi<YY>.phtml?id=12320` (YY = 2001..2025). |
| Yearly "итоги" page | `/common/itogi<YY>.phtml?id=12320` | (listed, not fetched) | *Unknown — needs verification* of structure. |
| Frameset pages | `/Texts/rus<N>/<slug>/frame<...>.htm` | `…/rus17/Gazavat_name/frametext1.htm` (listed in alpha index) | `<!DOCTYPE ... Frameset>` doctype. *Not fetched* in this audit. Inner frame URLs need a follow-up fetch to characterise. |

### 4.2 The stable identifier

- For `.phtml` pages the stable identifier is the **`id` query parameter**
  (e.g. `id=577` for Iordan's Getica part 2). It is **unique per page**, not
  per work — `text1.phtml`, `text2.phtml`, `pred.phtml` of the same work each
  have a different `id`.
- For `.htm` pages there is **no `id`**; the stable identifier is the full
  path (e.g. `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm`).
- The collector should store **both** the full URL and (when present) the
  numeric `id`, and treat the full URL as the canonical key for `.htm` pages.

### 4.3 Relative URLs (IMPORTANT — verified)

Many in-page links are **relative**, sometimes with `../../` prefixes:

- The homepage links to itogi as `../../common/itogi.phtml?id=101` — resolved
  against the homepage URL `/` this becomes `/common/itogi.phtml?id=101`
  (i.e. the `../../` is effectively a no-op because the homepage is at the
  root, but the parser MUST still resolve it correctly with
  `urllib.parse.urljoin`).
- Alpha-index pages link to works as `../../Texts/rus<N>/<slug>/<file>.phtml?id=NNNN`
  (verified in `alpha_G.html`). Resolved against
  `/haupt-Dateien/index-Dateien/G.phtml` this becomes
  `/Texts/rus<N>/<slug>/<file>.phtml?id=NNNN`.
- The `kavkaz.html` catalog links to documents as
  `Kavkaz/<century>/<period>/<slug>/<file>.htm` (relative to
  `/Texts/Dokumenty/`). Some entries cross-reference other regions, e.g.
  `../rus6/Pallas_2/text2.htm` (relative to `/Texts/Dokumenty/` →
  `/Texts/rus6/Pallas_2/text2.htm`).
- Image gallery pages (`karten.phtml`) link to images as bare relative
  filenames (`1.JPG`, `2.JPG`) — resolved against the page's own URL.

**Always use `urllib.parse.urljoin(page_url, href)`** to resolve links.

---

## 5. Page-type taxonomy

Proposed `page_type` values, each backed by a verified URL:

| `page_type` | Example URL (verified) | Key selectors / structure | Notes |
|---|---|---|---|
| `home` | `https://www.vostlit.info/` | `#headmenu` (А..Я + Документы), `#main` holds featured docs, `#leftmenu`/`#rightmenu` chrome, ad blocks `<div class="pubbl_sign">Реклама:</div>`. | Featured-docs list in `#main` has ~446 distinct `/Texts/rus...` links. |
| `alpha_index` | `…/haupt-Dateien/index-Dateien/G.phtml?id=2044` | `#main` (and `#spisalf` wrapper) holds entries. Each entry is a `<p>` containing a `<font color="#336633" face="Arial" size="3">` block. | Lists **works**, one `<p>` per work (an author with several works appears as several `<p>`s, or as one `<p>` with several work-titles). See §6.1. |
| `documents_hub` | `…/Texts/Dokumenty/index.phtml?id=2070` | `#main` lists 45 region links (`<region>.html`), each in a `<p>`. | Entry point to regional catalogs. |
| `region_catalog` | `…/Texts/Dokumenty/kavkaz.html` | **No `#main`**. Body holds 3 `<table width="100%">`s: table 0 = early/medieval section (64 rows × 3 cols), table 1 = chronological 18th–19th c. (285 rows × 3 cols), table 2 = footer. Each `<td>` = one document entry. | Plain `.html`, no site chrome. 750 KB for the Caucasus page. |
| `itogi_index` | `…/common/itogi.phtml?id=101` | `#main` holds 25 `<a>` yearly links `itogi<YY>.phtml?id=12320`. | Simple yearly-archive index. |
| `document_text` (`.phtml`) | `…/rus/Iordan/text2.phtml?id=577` | `<title>` = `AUTHOR->WORK->PART`. `#main` holds `<h4>` author, `<h2>` work, body `<p>`s; `#dann` (nested inside `#main` at the end) holds the citation. | Full site chrome. See §6.2. |
| `document_text` (`.htm`, "bare") | `…/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm` | **No chrome, no `#main`**. `<title>` often just `-` or a single word. Body holds `<p align="center"><strong><font>TITLE</font></strong></p>` + `<p>` body paragraphs + `<hr/>` + `<p align="center"><big>Комментарии</big></p>` + note `<p>`s + citation `<p><small><font color="#800040">…</font></small></p>`. | Distinct enough to deserve a parser branch. See §6.3. |
| `document_excerpt` | `…/rus9/Haukal/otryv2.phtml?id=1688` (listed on home, not fetched) | *Unknown — needs verification.* Likely same structure as `document_text` `.phtml`. | The `otryv<M>.phtml` filename signals "отрывок" (excerpt). |
| `notes_page` | `…/rus/Iordan/primtext6.phtml` | `#main` holds `<h5>Комментарии</h5>` then `<p align="JUSTIFY"><strong>N</strong>. <text></p>` per note. | No `id` query. Linked from the parent document_text page. See §7. |
| `image_gallery` | `…/rus13/Sirvan_Derbend/karten.phtml?id=1906` | `#main` holds `<h4>КАРТЫ</h4>` + `<p>`s each with `<a href="N.JPG" target="_blank"><font color="#800000">label</font></a> <big>(NN кб.)</big>`. | Image hrefs are bare relative filenames. See §8. |
| `collection_index` | `…/Kavkaz/VI/Dag_chron/index.htm` | Bare `.htm`. Body holds `<p align="center"><font color="#000000" size="6">TITLE</font></p>` + per sub-work `<p align="center"><font color="#336633" size="4">SUBWORK</font><br/><a href="...">Текст</a></p>`. | Index to a multi-work collection. See §6.4. |
| `bibliography` | `…/rus10/Meier/lit.phtml?id=295` (listed in alpha_G, not fetched) | *Unknown — needs verification.* Filename `lit.phtml` signals "Литература". | Likely a `.phtml` with `#main` listing references. |
| `frameset` | `…/rus17/Gazavat_name/frametext1.htm` (listed, not fetched) | `<!DOCTYPE ... Frameset>` (confirmed for `primtext6.phtml` which surprisingly used Frameset doctype but had no `<frame>`). | *Needs verification*: do `frame*.htm` files actually define frames, or are they plain docs? The name suggests framesets. |

---

## 6. Document-text page anatomy (detailed)

### 6.1 Alphabetical index page (verified on `G.phtml?id=2044`)

- Container: `<div id="main">` (with `<div id="spisalf">` as a logical wrapper).
- Each entry is a `<p>` whose first child is typically
  `<font color="#336633" face="Arial" size="3">`. Inside that `<font>`:
  - First text node (before any `<a>` or `<br/>`): **the header in ALL CAPS**
    — either the author name (e.g. `ГАЕК, ВАЦЛАВ`) or, for anonymous works,
    the work title itself (e.g. `ГАЗАВАТ-НАМЕ`, `ГАЛЛЬСКАЯ ХРОНИКА 452 ГОДА`).
  - Optionally followed by further plain-text nodes giving the **work title
    in mixed case** (e.g. `Чешская хроника`, `Газават-наме`). An anonymous
    work often repeats its title in mixed case here.
  - A series of `<br/>`-separated `<a href="...">` tags, each a **part link**
    with labels like `Предисловие`, `Введение`, `Текст`, `Часть 1`,
    `Книга I`, `Публикация 1961 г.`, `Рецензия`, `Карты`, `Глоссарий`,
    `Сокращения`, `Литература`, etc.
- A single `<p>` can contain **multiple works** by the same author
  (verified: `ГАЛЬФРИД МОНМУТСКИЙ` `<p>` contains both `История бриттов` and
  `Жизнь Мерлина`). Distinguishing a new work title from a part-link label
  requires checking whether the text node is inside an `<a>` (part link) or
  not (work title) — both are plain text in the same `<font>`.
- 710 `/Texts/` links were counted on the letter-Г page alone.
- **Two link flavors** appear in the alpha index:
  - `../../Texts/rus<N>/<slug>/<file>.phtml?id=NNNN` — the standard
    `.phtml` document (has chrome).
  - `../../Texts/rus<N>/<slug>/frame<...>.htm` — frameset-style pages
    (e.g. `frametext1.htm`, `framepred1.htm`). These are common for older
    multi-part works (Gazavat-name, Meier, Gall, Rustam Raza, etc.).

**Parsing rule for `alpha_index`:**
1. `soup.find(id="main")`.
2. Iterate over direct-child `<p>` elements.
3. For each `<p>`, descend into the `<font color="#336633">` (or just take
   the `<p>`'s contents if no `<font>`).
4. Walk children in order: plain text → header/work-title; `<a href>` →
   part link (label = `a.get_text()`, url = `urljoin(page_url, a["href"])`).
5. The first plain-text node is the CAPS header (author or anonymous title).

### 6.2 `.phtml` document-text page (verified on 5 pages)

Verified pages: `Iordan/text2.phtml?id=577`, `Tunmann/pred.phtml?id=1541`,
`Esai/pred2.phtml?id=483`, `Wachushti/text11.phtml?id=251`,
`Sirvan_Derbend/karten.phtml?id=1906`.

Common skeleton:

```
<title>AUTHOR->WORK->PART</title>           # breadcrumb, "->"-separated, ALL CAPS
<body>
  <center>logo, header, headmenu (А..Я + Документы)</center>
  <div id="main">                            # THE main content container
    <h4>AUTHOR</h4>                          # author name (matches title part 1)
    <h2>WORK TITLE</h2>                      # work title (matches title part 2)
    <p align="CENTER"><strong><small>foreign-language title</small></strong></p>  # optional
    <p align="center"><b>SECTION HEADING</b></p>             # e.g. ПРЕДИСЛОВИЕ
    <p align="JUSTIFY">body paragraph...</p>                 # body text
    ... more <p>s ...
    [<h5>Комментарии</h5>                     # optional inline notes section
       <p align="JUSTIFY"><strong>N</strong>. note text</p>
       ...]
    <div id="dann">                           # citation block, NESTED in #main
      <p>Текст воспроизведен по изданию: ...</p>
      © текст - ...
      © сетевая версия - ...
      © OCR - ...
      © дизайн - Войтехович А. 2001
      © publisher.
    </div>
  </div>
  <div id="leftmenu">...</div>
  <div id="footmenu">...</div>
  <div id="rightmenu">...</div>
```

Key selectors (verified on every sampled `.phtml` doc):

| Field | Selector | Example value (Iordan text2) |
|---|---|---|
| Breadcrumb title | `soup.title.string` | `"ИОРДАН->О ПРОИСХОЖДЕНИИ И ДЕЯНИЯХ ГЕТОВ->ЧАСТЬ 2"` |
| Author | `#main > h4` (first `<h4>` in `#main`) | `"ИОРДАН"` |
| Work title | `#main > h2` (first `<h2>` in `#main`) | `"О ПРОИСХОЖДЕНИИ И ДЕЯНИЯХ ГЕТОВ"` |
| Section heading | `#main p[align=center] > b` | `"ПРЕДИСЛОВИЕ"` |
| Body paragraphs | `#main p[align=JUSTIFY]` (and `#main p:not([align])`) | body text |
| Inline page-number marker | `#main font[color="#800000"] > strong` | `[89]`, `[90]` |
| Inline chapter/section marker (source ed.) | `#main font[color="#FF0000"] > strong` (sometimes `<em>`-wrapped) | `{142}`, `{143}` |
| Inline footnote reference (when blue) | `#main font[color="#0000FF"] > sup > strong` | `421`, `422` (Iordan) |
| Inline footnote reference (when uncoloured) | `#main strong > sup` (no `<font>` wrapper) | `1`, `2`, `3` (Tunmann) |
| Inline editorial note (in `.htm` docs) | `font[color="#FF0000"][size="3"]` | explanatory gloss |
| Citation / source block | `#main div#dann` (or `soup.find(id="dann")`) | `"Текст воспроизведен по изданию: ..."` |
| Citation text | `#dann p` first text node | `"Текст воспроизведен по изданию: Иордан. О происхождении и деяниях гетов. Спб. Алетейя. 1997"` |
| Copyright lines | `#dann` text after the `<p>` (plain text + `<br/>`) | `© текст - Скржинская Е. Ч. 1960` etc. |
| Notes section (inline, when present) | `#main h5` + following `<p>` siblings until `#dann` | Tunmann has `<h5>Комментарии</h5>` |

**Variations verified across the 5 sampled `.phtml` docs:**

- **Footnote reference markup VARIES.**
  - Iordan: `<font color="#0000FF"><sup><strong>N</strong></sup></font>` (blue).
  - Tunmann: `<strong><sup>N</sup></strong>` (no colour, no `<font>`).
  - Esai, Wachushti: **no `<sup>` at all** in the body (the page has no
    numbered footnote refs in the running text — they may be on a separate
    notes page reached via the alpha index).
  - The parser must therefore look for **both** patterns:
    `sup` inside `font[color="#0000FF"]` AND bare `strong > sup`.
- **Inline notes section VARIES.**
  - Tunmann has `<h5>Комментарии</h5>` directly in `#main` after the body,
    with notes as `<p><strong>N</strong>. text</p>`.
  - Iordan has **no** inline notes section — instead, the top of `#main`
    has a paragraph:
    `Ввиду большого объема комментариев их можно посмотреть здесь`
    followed by links `401-500`, `501-600`, …, `801-838` pointing to
    `primtext6.phtml` … `primtext10.phtml`.
  - Esai, Wachushti: no inline notes section observed (notes may be on
    separate pages).
- **Page-number markers (`<font color="#800000">[N]</font>`)** are present
  in Iordan (33), Tunmann (10), Esai (4), Wachushti (33) but absent from
  the `karten.phtml` image-gallery page.
- **Chapter markers (`<font color="#FF0000">{N}</font>`)** were observed
  only in Iordan (the source edition — Mommsen — has its own chapter
  numbering). Other docs may use red text for different purposes (e.g. the
  `.htm` Dagestan doc uses `#FF0000` for inline editorial glosses).
- **`#dann` is NESTED inside `#main`** (verified on Tunmann, Iordan). When
  extracting body text from `#main`, you MUST exclude `#dann` (and any
  `#dann`-following content) or the citation/copyright lines will leak into
  the body. Recommended:
  ```python
  dann = main.find(id="dann")
  if dann:
      # extract dann first, then remove it from main before reading body
      citation_html = str(dann)
      dann.extract()
  body_text = main.get_text("\n", strip=True)
  ```

### 6.3 `.htm` "bare" document-text page (verified on `Dagestan_poddanstvo_1792/text.htm`)

This is the document flavor served from `/Texts/Dokumenty/<region>/...` paths
(often the smaller archival documents — letters, reports, etc.). It is
**structurally different** from the `.phtml` flavor:

```
<title>-</title>                            # often just "-" or a short word; NOT a breadcrumb
<body background="../../../../../../bge0012.JPG">   # relative background image, NO #main, NO headmenu
  <p align="center"><strong><font color="#000000">"MAIN TITLE"</font></strong></p>
  <p align="center"><strong><font size="3">subtitle / date</font></strong></p>
  <p>body paragraph...</p>
  <p>body paragraph... <font color="#FF0000" size="3">inline editorial gloss</font> ...</p>
  ...
  <p align="right"><small>архивный шифр (archive ID)</small></p>
  <hr/>
  <p align="center"><big>Комментарии</big></p>     # notes section header
  <p><font color="#000000">1. note text</font></p>
  <p><font color="#000000">2. note text</font></p>
  ...
  <p><small><font color="#800040"><strong>Текст воспроизведен по изданию: ...</strong></font></small></p>
  <p><small>
     <font color="#800040">©</font> <b><font color="#800040"><strong>текст - ...</strong></font></b><br/>
     ... more © lines in #800040 ...
  </small></p>
</body>
```

Key selectors (verified on `Dagestan_poddanstvo_1792/text.htm`):

| Field | Selector | Notes |
|---|---|---|
| Title (main) | `body > p[align=center]:first-child strong font[color="#000000"]` | All-caps quoted title. |
| Subtitle / date | `body > p[align=center] strong font[size="3"]` | e.g. `"К вопросу о вхождении дагестанских владельцев в состав России. 1792 г."` |
| Body | all `<p>` that are not `[align=center]` and not after the `<hr/>` | No `#main` container. |
| Inline editorial gloss | `font[color="#FF0000"][size="3"]` | Red explanatory insertions. |
| Archive ID | `p[align=right] small` | e.g. `"ГААсО. Ф. 476. Оп. 5. Д. 124. Л. 8. Копия."` |
| Notes-section break | the `<hr/>` followed by `<p align="center"><big>Комментарии</big></p>` | Header uses `<big>`, NOT `<h5>`. |
| Individual note | after the Коммент. header, `<p><font color="#000000">N. text</font></p>` | Note number is plain text, not `<strong>`. |
| Citation | `<p><small><font color="#800040"><strong>Текст воспроизведен по изданию: ...</strong></font></small></p>` | Maroon `#800040`. |
| Copyright lines | following `<p><small>` with `<font color="#800040">©</font> ...` | Maroon `#800040`. |

**Important differences from the `.phtml` flavor:**
- No `#main`, no `#dann`, no `#headmenu` — the page is essentially bare
  content with a background image.
- The citation block is identified by the colour `#800040` (maroon) and the
  `<small>` wrapper, NOT by a `#dann` id.
- Notes section uses `<big>Комментарии</big>` not `<h5>Комментарии</h5>`.
- The `<title>` tag is useless for breadcrumb purposes (often just `"-"`).
- The page's path (`/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm`)
  is the only reliable identifier — there is no `id` query param.

### 6.4 Collection-index `.htm` page (verified on `Dag_chron/index.htm`)

Used as the table-of-contents for a multi-work collection (e.g. the 13
Dagestan chronicles). Structure:

```
<title>ПРЕДИСЛОВИЕ</title>     # or whatever the first linked section is
<body background="../../../../../bge0012.JPG">
  <p align="center"><font color="#000000" size="6">ДАГЕСТАНСКИЕ ИСТОРИЧЕСКИЕ СОЧИНЕНИЯ</font></p>
  <p align="center"><a href="pred.phtml?id=396"><font color="#336633" ...>Предисловие</font></a></p>
  <p align="center">
    <font color="#336633" size="4">ДЕРБЕНД-НАМЕ</font><br/>
    <a href="Derbend_name/pred.phtml?id=397"><font color="#336633">Предисловие</font></a><br/>
    <a href="Derbend_name/frametext.htm"><font color="#336633">Текст</font></a>
  </p>
  ... one <p> per sub-work ...
  <p align="center"><a href="lit.htm">Литература</a><br/><a href="sokr.htm">Сокращения</a></p>
</body>
```

- Each sub-work is a `<p align="center">` whose first child is a
  `<font color="#336633" size="4">` (size 4 = sub-work title) followed by
  `<a>` links (size 3) to its parts.
- Links are **relative to the index page's directory** (e.g.
  `Derbend_name/frametext.htm` resolves to
  `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/Derbend_name/frametext.htm`).
- Some sub-work links use `.phtml?id=NNN` (e.g. `pred.phtml?id=396`), others
  use bare `.htm` (e.g. `Derbend_name/frametext.htm`) — the two flavors
  coexist within one collection.

---

## 7. Footnotes / bibliography / notes extraction rules

### 7.1 Three kinds of inline numeric marker in `.phtml` body text

(All three verified on `Iordan/text2.phtml?id=577`; some verified on Tunmann
and others.)

| Marker | HTML | Meaning | Action |
|---|---|---|---|
| `[N]` maroon | `<font color="#800000"><strong>[N]</strong></font>` | Page break in the **Russian print edition** being reproduced. | Record as a page-break anchor in the body; do NOT treat as a footnote. |
| `{N}` red | `<font color="#FF0000"><strong>{N}</strong></font>` (often `<em>`-wrapped) | Chapter/section number in the **source/original edition** (e.g. Mommsen's chapter numbering for Iordan). | Record as a source-chapter anchor. |
| `N` blue superscript | `<font color="#0000FF"><sup><strong>N</strong></sup></font>` | **Footnote reference.** The note text lives on a separate `primtext<M>.phtml` page (range-batched, e.g. notes 401–500 on `primtext6.phtml`). | Record the note number; fetch the corresponding notes page to retrieve the text. |
| `N` uncoloured superscript | `<strong><sup>N</sup></strong>` | **Footnote reference** (alternative markup, verified on Tunmann). The note text is in the inline `<h5>Комментарии</h5>` section further down the same page. | Record the note number; look for the inline notes section on the same page. |

**No `<a class="note">`, no `<a href="#fnN">`, no `<a name="fnN">` patterns
were found on any sampled page.** The site does not use hyperlink-style
footnote anchors. Inline markers are purely typographic (coloured `<font>`
+ `<sup>`).

### 7.2 Notes section (inline, on the same page) — verified on Tunmann

When notes are inline (no separate notes page), the section appears at the
**bottom of `#main`, before `#dann`**:

```html
<h5>Комментарии</h5>
<p align="JUSTIFY"><strong>1</strong>. note text...</p>
<p align="JUSTIFY"><strong>2</strong>. note text...</p>
```

Extraction:
1. `h5 = main.find("h5", string="Комментарии")` (or `h5 = main.find("h5")`
   — there is usually only one `<h5>`).
2. Iterate `h5.find_next_siblings("p")` until you hit `#dann` (or the end of
   `#main`).
3. For each `<p>`, the leading `<strong>N</strong>` is the note number; the
   remaining text is the note body.

### 7.3 Notes page (separate, range-batched) — verified on `Iordan/primtext6.phtml`

URL pattern: `/Texts/rus<N>/<slug>/primtext<M>.phtml` (**no `id` query**).
The parent `.phtml` document links to these at the top of `#main`:

```html
Ввиду большого объема комментариев их можно посмотреть здесь
<a href="primtext6.phtml" target="_blank">401-500</a>
<a href="primtext7.phtml" target="_blank">501-600</a>
...
```

Notes-page structure (verified):
```html
<title>КОММЕНТАРИИ К ТЕКСТУ</title>
<div id="main">
  <h5>Комментарии</h5>
  <p align="JUSTIFY"><strong>421</strong>. «Ab hac luce migravit» — обычное выражение...</p>
  <p align="JUSTIFY"><strong>422</strong>. Атанарих, или Айтанарих, — король везеготов...</p>
  ...
</div>
```

So the notes-page selector is the SAME as the inline-notes selector
(`<h5>Комментарии</h5>` + `<p><strong>N</strong>. text</p>`), just on a
dedicated page. The note number range is announced in the link text on the
parent page (e.g. `401-500`).

### 7.4 Bibliography / source citation ("Текст воспроизведен по изданию")

Two flavors (both verified):

**`.phtml` flavor — `#dann` block:**
```html
<div id="dann">
  <p>Текст воспроизведен по изданию: Иордан. О происхождении и деяниях гетов. Спб. Алетейя. 1997</p>
  © текст - Скржинская Е. Ч. 1960<br/>
  © сетевая версия - Каюмов И. 2002<br/>
  © OCR - Вдовиченко С.; Колоскова Л. 2005<br/>
  © дизайн - Войтехович А. 2001<br/>
  © Алетейя. 1997
</div>
```
Sometimes preceded by a translator line: `(пер. Е. Ч. Скржинской)<br/>`
or `(пер. Н. Т. Накашидзе)`.

**`.htm` flavor — maroon `<small>` block:**
```html
<p><small><font color="#800040"><strong>Текст воспроизведен по изданию: "Принимать их так, как подданных ея императорского величества". ... 1792 г. // Исторический архив, № 4. 2003</strong></font></small></p>
<p><small>
   <font color="#800040">©</font> <b><font color="#800040"><strong>текст - Викторин И. И. 2003</strong></font></b><br/>
   <font color="#800040">©</font> <b><font color="#800040"><strong>сетевая версия - Тhietmar. 2006</strong></font></b><br/>
   ...
</small></p>
```

**Extraction rule (both flavors):** search the page text for the regex
`Текст\s+воспроизведен по изданию:\s*(.+)` — the matched line (up to the
first `<br/>` or end of `<p>`) is the source citation. Then collect
`©\s*([^\n]+?)(?:<br/>|\n)` lines for the copyright/attribution lines.

A separate `lit.phtml` ("Литература") page may also exist per work (listed
in the alpha index, e.g. `Meier/lit.phtml?id=295`) — *Unknown — needs
verification* of its structure (likely a `.phtml` with `#main` listing
references).

### 7.5 Other auxiliary page types (listed in alpha index, not fetched)

The alpha index reveals these per-work auxiliary filenames:
- `pred.phtml` / `pred1.phtml` / `pred2.phtml` — предисловие (preface).
- `vved.phtml` / `framevved1.htm` — введение (introduction).
- `text<M>.phtml` / `frametext<M>.htm` — main text parts.
- `otryv<M>.phtml` / `otr<M>.phtml` — отрывок (excerpt).
- `primtext<M>.phtml` — примечания/комментарии (notes).
- `lit.phtml` — литература (bibliography).
- `sokr.phtml` / `sokr.htm` — сокращения (abbreviations).
- `glossar.phtml` — глоссарий (glossary).
- `izd.phtml` — от издателя (publisher's note).
- `avtor.phtml` — от автора (author's note).
- `zakl.phtml` — заключение (conclusion).
- `chrono.phtml` — хронология (chronology).
- `karten.phtml` / `karten.htm` — карты (maps).
- `recenz_*.phtml` / `recenz_*.htm` — рецензия (review).
- `framepred<M>.htm` / `frametext<M>.htm` / `framevved<M>.htm` /
  `frameposl<M>.htm` — frameset versions of the above.

All of these are likely either `.phtml` (chrome) or `.htm` (bare) and should
be parseable with the two document-text branches in §6.2/§6.3.

---

## 8. Images & scans handling (verified on `Sirvan_Derbend/karten.phtml`)

The image-gallery page (`karten.phtml` or `karten.htm`) is a simple list:

```html
<div id="main">
  <h4>КАРТЫ</h4>
  <h2></h2>
  <p align="center"><big>(Открываются в новом окне)</big></p>
  <p align="left">
    <strong>
      <a href="1.JPG" target="_blank">
        <font color="#800000">Родословная лайзанской ветви Йазидидов.</font>
      </a>
    </strong>
    <big>(48 кб.)</big>
  </p>
  <p><strong><a href="2.JPG" target="_blank"><font color="#800000">Карта 1.</font></a></strong> <big>(220 кб.)</big></p>
  ...
</div>
```

- Image hrefs are **bare relative filenames** (`1.JPG`, `2.JPG`, …)
  resolved against the gallery page's URL. Final URL e.g.
  `https://www.vostlit.info/Texts/rus13/Sirvan_Derbend/1.JPG`.
- Each image has a **label** (in `<font color="#800000">`) and a **file-size
  annotation** (`<big>(NNN кб.)</big>`).
- Images open in a new tab (`target="_blank"`).
- No thumbnails — the gallery links directly to full-size `.JPG` files.

**Extraction rule for `image_gallery`:**
1. `soup.find(id="main")` (for `.phtml`) or just `soup.body` (for `.htm`).
2. For each `<a>` whose `href` ends in `.JPG`/`.jpg`/`.png`/`.gif`:
   - `url = urljoin(page_url, a["href"])`
   - `label = a.get_text(" ", strip=True)`
   - `size_note = a.find_next("big").get_text(strip=True)` if present.

Inline images (`<img>`) inside document-text pages were NOT observed in the
sampled pages — the site appears to favour text-only documents with images
segregated into dedicated `karten.*` pages. *Unknown — needs verification:*
whether any document-text page embeds inline scans.

---

## 9. Pagination / multi-part works (verified)

**There is no "next/prev" pagination on document-text pages.** A multi-part
work is presented as **separate, independently-linked pages** from the
alpha index (or regional catalog). Each part has its own URL and its own
`id`:

Examples from the alpha-Г index (verified):
- `Гальфрид Монмутский / История бриттов` → 6 separate links:
  `Предисловие`, `Главы 1-40`, `Главы 41-80`, `Главы 81-120`, `Главы 121-160`,
  `Главы 161-208` (each a different `text<M>.phtml?id=NNN`).
- `Галл Аноним / Хроника...` → `Публикация 1961 г.` (with `Предисловие`,
  `Книга I`, `Книга II`, `Книга III`, `Рецензия`) AND `Публикация 1979 г.`
  (different parts) — **two different editions of the same work**, listed
  as separate groups of links within one `<p>`.
- `Гакоген, Саббатай / Послание` → 11 links covering `От издателя`,
  `От автора`, `Введение. Часть 1`, `Введение. Часть 2`, `Текст`,
  `Указатели`, `Библиографический обзор`, `Послесловие. Часть 1`,
  `Послесловие. Часть 2`, `Избранная библиография`.

So a "work" is a **collection of part-pages** whose URLs share a common
prefix `/Texts/rus<N>/<slug>/` but differ in filename and `id`. To collect a
whole work, the parser must:
1. From the alpha index, group all `<a>` links that share the same
   `/Texts/rus<N>/<slug>/` path prefix into one work.
2. Optionally classify each part by filename:
   `pred*` = preface, `vved*` = introduction, `text*` = main text,
   `otryv*`/`otr*` = excerpt, `primtext*` = notes, `lit*` = bibliography,
   `sokr*` = abbreviations, `glossar*` = glossary, `karten*` = maps,
   `recenz_*` = review, `zakl*` = conclusion, `chrono*` = chronology,
   `izd*` = publisher's note, `avtor*` = author's note.

For `.htm` documents in the regional catalogs, the same grouping applies
but the path prefix is
`/Texts/Dokumenty/<region>/<century>/<period>/<slug>/`.

**Frameset pages (`frame*.htm`)** are listed in the alpha index for some
works (Gazavat-name, Meier, Gall, Rustam Raza, etc.). These were NOT
fetched in this audit. The filename pattern (`framepred1.htm`,
`frametext1.htm`, `framevved1.htm`, `frameposl1.htm`) suggests they are
HTML framesets that load the actual content into a sub-frame. *Needs
verification:* fetch one `frame*.htm` to confirm whether it defines a
`<frameset>` (and therefore needs a second fetch to get the inner frame
URL) or is just a normal page despite the name.

---

## 10. Caucasus & Dagestan material found

**The site has a dedicated, very large Caucasus catalog** at
`/Texts/Dokumenty/kavkaz.html` (750 KB, verified). It is the primary entry
point for Caucasus/Dagestan material. It is a plain `.html` file (no `id`,
no chrome) organised as a 3-column table, chronologically by century
(sections: VI, VII, IX, X, XIII, XIV, XV, XVI, XVII, XVIII, XIX).

The following Caucasus/Dagestan-relevant documents were **verified by URL**
in the kavkaz.html catalog (URLs are absolute paths under
`https://www.vostlit.info`):

| # | Title (as in catalog) | Date / period | URL path | Notes |
|---|---|---|---|---|
| 1 | ДАГЕСТАНСКИЕ ИСТОРИЧЕСКИЕ СОЧИНЕНИЯ (collection) | VI в.–1916 | `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/index.htm` | **Index to 13 Dagestan chronicles** (verified by fetch). See sub-list below. |
| 2 | АКТЫ, СОБРАННЫЕ Кавказской Археографической Комиссией | 1398–1866 | `/Texts/Dokumenty/Kavkaz/AKAK/Tom_1/index.htm` … `Tom_12/index.htm` | 12-volume AKAК collection. Each volume has its own `index.htm`. |
| 3 | МУХАММАД РАФИ АШ-ШИРВАНИ, История Дагестана | –1319 | `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/Muchammadrafi/text.htm` | "Тарих-и Дагестан". |
| 4 | МАТЕРИАЛЫ по средневековой истории Дагестана | сер. XIV в. | `/Texts/Dokumenty/Kavkaz/XIV/1340-1360/Mat_sredn_ist_dagestan/text.htm` | |
| 5 | МАТЕРИАЛЫ ПО ИСТОРИИ Горного Дагестана | 1431–1524 | `/Texts/Dokumenty/Kavkaz/XV/Mat_gorn_dagestan/text.htm` | |
| 6 | ЮЖНОДАГЕСТАНСКИЙ ХРОНОГРАФ | 1434–1712 | `/Texts/Dokumenty/Kavkaz/XV/1440-1460/Juznodag_chronograf/text.phtml` | `.phtml` (has chrome). |
| 7 | ИСТОРИЧЕСКИЕ СВЕДЕНИЯ О ДАГЕСТАНЕ из арабских рукописей | 1495–1796 | `/Texts/Dokumenty/Kavkaz/XV/1480-1500/Sved_ar_rukopis/text.htm` | |
| 8 | ДАГЕСТАНСКИЕ ДОКУМЕНТЫ XV–XVII вв. | 1499–1500 + | `/Texts/Dokumenty/Kavkaz/XV/Dag_dok1/text1.htm` (also `text2.htm`, `text3.htm`, `text4.htm`, `pred.htm`) | Multiple parts. |
| 9 | СРАЖЕНИЕ УЦМИЕВ В ДАГЕСТАНЕ и история сражений с иранцами | XVI в.–1720 | `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/O_borbe/text.htm` | "Уцмий" = Dagestan ruler title (Kaitag utsmi). |
| 10 | ДОКУМЕНТЫ О РАБСТВЕ В ДАГЕСТАНЕ | 1553–1657 | `/Texts/Dokumenty/Kavkaz/XVI/Dok_rabstvo_dagestan/text.htm` | |
| 11 | ПЕРЕЧЕНЬ ПОВИННОСТЕЙ которые получали Шамхал и Крым-Шамхал | XV в.? | `/Texts/Dokumenty/Kavkaz/XV/Perecen_povinnostej/text1.htm` | **Shamkhal of Tarki** — key Dagestan ruler. |
| 12 | Саййид Мухаммад, Письмо джамдатам Казикумуха | XV в. | `/Texts/Dokumenty/Kavkaz/XV/1440-1460/Sajjid_Muchammad/brief_kazikumuch.htm` | **Kazikumukh** (Ghazi-Ghumuq) — key Dagestan state. |
| 13 | ИСТОРИЯ ПОТОМКОВ МУХАММАДА КАЗИКУМУХСКОГО | — | `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/Ist_potomk_M/text.htm` (+ `pril1.htm`, `pril2.htm`, `pril3.htm`) | Kazikumukh dynasty. |
| 14 | ТАРИХИ ЭНДИРЕЙ | — | `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/Tarichi_Endirei/text.htm` | Endirey — Dagestan/Kumyk settlement. |
| 15 | ТАРИХИ КЫЗЛАРКАЛА | — | `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/Tarihi_Kizlarkala/frametext.htm` | Kizlyar. Frameset. |
| 16 | О ВХОЖДЕНИИ ДАГЕСТАНА В ПОДДАНСТВО РОССИИ | 1792 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm` | **Verified by fetch** (§6.3). |
| 17 | ДОКУМЕНТЫ ОБЫЧНОГО ПРАВА Дагестана | XVIII–XIX вв. | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dok_ob_prav_Dagestan/text.htm` | Adat (customary law). |
| 18 | ШЕЙХ МАНСУР АНАПСКИЙ | 1785–1791 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Sejch_Mansur/text.htm` | Sheikh Mansur — early Caucasian War leader. |
| 19 | СЕРЕБРОВ А. Г., Историко-этнографическое описание Дагестана | 1796 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Serebrov_A_G/opisanie_dagestana_1796.htm` | |
| 20 | СИМОНОВИЧ Ф. Ф., Описание южного Дагестана | 1796 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Simonovic_F_F/opis_juz_dagestana_1796.htm` | |
| 21 | ДРЕНЯКИН И. Т., Описание Ширвана | 1796 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Drenjakin_I_T/text.htm` | |
| 22 | НОГМОВ Ш. Б., История адыхейского народа | –1771 | `/Texts/Dokumenty/Kavkaz/...` (linked from table 0) | Adyghe (Circassian). |
| 23 | КАРАУЛОВ Н. А., Сведения арабских писателей о Кавказе, Армении и Адербейджане | — | `/Texts/Dokumenty/Kavkaz/Karaulov/frametext1.htm` … `frametext9.htm` | 9 issues (al-Istakhri, Ibn Khordadbeh, Ibn Rustah, etc.). Framesets. |
| 24 | ГИЛЬДЕНШТЕДТ И. А. | 1760s–70s | `/Texts/Dokumenty/Kavkaz/XVIII/1760-1780/Gildensdedt_2/text1.htm` (+ `text2.htm`) | Two editions. |
| 25 | РЕЙНЕГГС Я., Описание Кавказа | 1779–1783 | `/Texts/Dokumenty/Kavkaz/XVIII/1760-1780/Reineggs/text1.htm` (+ `text2.htm`) | |
| 26 | ГМЕЛИН С.-Г. | 1774 | `/Texts/Dokumenty/Kavkaz/XVIII/1760-1780/Gmelin/text1.htm` | |
| 27 | ФАЛЬК И. П. | 1773 | `/Texts/Dokumenty/Kavkaz/XVIII/1760-1780/Falck_Johann_Peter/text1.htm` | |
| 28 | ГЕОРГИ И. Г. | 1776 | `/Texts/Dokumenty/Kavkaz/XVIII/1760-1780/Gottlib_Georgi/text1.htm` | |
| 29 | ПАЛЛАС П. С. | 1793–1794 | `/Texts/rus6/Pallas_2/text1.htm` (+ `text2.htm`) | Cross-referenced from `rus6` (Russia section). |
| 30 | О КАВКАЗСКИХ ПРАВИТЕЛЯХ | 1785–1790 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Kavk_praviteli/text1.htm` | |
| 31 | КАВКАЗ в 1787–1799 годах | 1787–1799 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Kavkaz_1787_1799/text11.htm` (+ `text12.htm`, `text2.htm`, appendices) | |
| 32 | МАТЕРИАЛЫ для истории Северного Кавказа | 1787–1792 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Mat_sev_kavk_1787_1792/text1.htm` (+ `pril11.htm`) | |
| 33 | КАВКАЗСКИЙ ВЕКТОР российской политики | 1796–1864 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Kavkaz_vektor_II/...` | 2 vols. |
| 34 | РОМАНОВСКИЙ Д. И., Кавказ и Кавказская война | 1795–1859 | `/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Romanovskij_D_I/text1.htm` (+ `pred.htm`) | |
| 35 | КАБАРДИНО-РУССКИЕ ОТНОШЕНИЯ в XVI–XVIII вв. | 1552–1791 | `/Texts/Dokumenty/Kavkaz/XVI/Russ_Kab_otn_1/index.htm` (+ `Russ_Kab_otn_2/`, `karten.htm`) | 2 vols + maps. |
| 36 | РУССКО-ЧЕЧЕНСКИЕ ОТНОШЕНИЯ (2-я пол. XVI–XVII вв.) | 1586–1698 | `/Texts/Dokumenty/Kavkaz/XVI/Russ_Chech_otn/index.htm` | |
| 37 | КАСПИЙСКОЕ МОРЕ в арабских источниках | — | `/Texts/Dokumenty/Kavkaz/...` (linked from table 0, parts Введение / Часть 1 / Часть 2) | |

**Dagestan chronicles sub-list** (verified by fetching `Dag_chron/index.htm`):

The collection "ДАГЕСТАНСКИЕ ИСТОРИЧЕСКИЕ СОЧИНЕНИЯ" at
`/Texts/Dokumenty/Kavkaz/VI/Dag_chron/` contains 13 sub-works, each with its
own subdirectory:

| Sub-work | URL (relative to `Dag_chron/`) |
|---|---|
| Предисловие | `pred.phtml?id=396` |
| ДЕРБЕНД-НАМЕ | `Derbend_name/pred.phtml?id=397`, `Derbend_name/frametext.htm` |
| АХТЫ-НАМЕ | `Achty_name/text.phtml?id=398` |
| ИСТОРИЯ АБУ МУСЛИМА | `Ist_Abu_Muslim/text.htm` |
| "ТАРИХ-И ДАГЕСТАН" МУХАММАДРАФИ | `Muchammadrafi/text.htm` |
| ИСТОРИЯ МАЗА (пространная редакция) | `Ist_Maza/frametext.htm`, `Ist_Maza/pril.htm` |
| ИСТОРИЯ МАЗА (краткая редакция) | `Ist_Maza_2/text.htm`, `Ist_Maza_2/pril1.htm`, `Ist_Maza_2/pril2.htm` |
| ИСТОРИЯ КАРАКАЙТАГА | `Ist_Karakaitaga/text.htm` |
| ИСТОРИЯ ИРХАНА | `Ist_Irchan/text.htm` |
| ИСТОРИЯ ГИРЕЙХАНА | `Ist_Gireichana/text.htm` |
| ИСТОРИЯ ПОТОМКОВ МУХАММАДА КАЗИКУМУХСКОГО | `Ist_potomk_M/text.htm`, `Ist_potomk_M/pril1.htm`, `pril2.htm`, `pril3.htm` |
| О БОРЬБЕ ДАГЕСТАНЦЕВ ПРОТИВ ИРАНСКИХ ЗАВОЕВАТЕЛЕЙ | `O_borbe/text.htm` |
| ТАРИХИ ЭНДИРЕЙ | `Tarichi_Endirei/text.htm` |
| ТАРИХИ КЫЗЛАРКАЛА | `Tarihi_Kizlarkala/frametext.htm` |
| (collection-level) Литература / Сокращения | `lit.htm`, `sokr.htm` |

**Other Caucasus-relevant documents found OUTSIDE the kavkaz.html catalog**
(verified by fetching or by listing on the homepage / alpha index):

| Title | Author | URL path | Period | Notes |
|---|---|---|---|---|
| Краткая история страны албанской | Есаи Хасан-Джалалян | `/Texts/rus/Esai/pred2.phtml?id=483` | 1702–1722 | Caucasian Albania / Artsakh. **Verified by fetch.** |
| История царства грузинского | Вахушти Багратиони | `/Texts/rus6/Wachushti/text11.phtml?id=251` | 1745 | Georgia. **Verified by fetch.** |
| История Ширвана и Дербенда | (anonymous, ed. Minorsky) | `/Texts/rus13/Sirvan_Derbend/karten.phtml?id=1906` | — | Shirvan & Derbend (Dagestan). **Maps page verified by fetch**; text pages exist with other `id`s (not fetched). |
| Крымское ханство | Иоганн Тунманн | `/Texts/rus5/Tunmann/pred.phtml?id=1541` | 1770s | Crimea (Caucasus-adjacent). **Verified by fetch.** |
| Газават-наме | (anonymous) | `/Texts/rus17/Gazavat_name/framepred1.htm` | — | Caucasian War / Dagestan chronicle. Listed in alpha-Г (not fetched; frameset). |

**Honesty note:** the kavkaz.html catalog contains **far more** Caucasus
material than is listed in the table above (1520 unique Caucasus/Dagestan-
keyword-matching links were found by scanning all `<a>` in the catalog). The
37 entries above are the most directly Dagestan/Caucasus-relevant ones I
could identify by title-keyword match. A full enumeration would require
parsing the entire 750 KB catalog — straightforward but beyond the scope of
this audit. The collector should treat `kavkaz.html` as the authoritative
Caucasus/Dagestan discovery source and parse it in full.

---

## 11. Parsing risks & unknowns

### 11.1 Risks (things that will bite the parser)

1. **Two document flavors.** `.phtml` (chrome, `#main`/`#dann`) and `.htm`
   (bare, no chrome) coexist even within the same collection. The parser
   MUST branch on URL suffix AND on presence of `#main`. A single
   "document_text" function will not handle both correctly.
2. **`#dann` is nested inside `#main`.** Body-text extraction from `#main`
   must exclude `#dann` or the citation/copyright text leaks into the body.
3. **Footnote-reference markup varies.** Iordan uses
   `<font color="#0000FF"><sup><strong>N</strong></sup></font>`; Tunmann uses
   `<strong><sup>N</sup></strong>` (no `<font>`). The parser must look for
   `<sup>` inside the body and capture its number regardless of the
   surrounding colour.
4. **Three inline numeric markers** (`[N]` maroon page, `{N}` red chapter,
   `N` blue/uncoloured sup footnote) are distinguishable ONLY by colour and
   by bracket style. A parser that ignores colour will conflate them.
5. **No hyperlink-style footnote anchors.** Don't look for `<a href="#fnN">`
   or `<a name="fnN">` — they don't exist. Footnotes are linked only at the
   page-top level (`primtext6.phtml` etc.) with range labels (`401-500`).
6. **Relative URLs with `../../`.** Always `urljoin`. The homepage's itogi
   link `../../common/itogi.phtml?id=101` is a particularly nasty case
   (it works only because the homepage is at `/`).
7. **The `id` query is per-page, not per-work.** Don't assume
   `text1.phtml?id=1906` exists because `karten.phtml?id=1906` does. The
   collector must follow links from the alpha index / regional catalog to
   discover each part page's correct `id`.
8. **404 backend is Apache; live site is nginx.** A missing page returns an
   Apache 404 (default body, `iso-8859-1` charset) — do NOT try to
   windows-1251-decode 404 bodies; check `r.status_code == 200` first.
9. **`<title>` is unreliable for `.htm` docs** (often just `"-"` or a single
   word). Use the in-body `<p align="center"><strong><font>` title instead.
10. **`<title>` breadcrumb uses `->`** (ASCII hyphen + greater-than) as
    separator for `.phtml` docs. Splitting on `->` gives `[author, work,
    part]` — useful for structured metadata, but the separator is also a
    valid substring within some titles, so split only on the FIRST two
    occurrences.
11. **Ad blocks on the homepage.** `<div class="pubbl_sign">Реклама:</div>`
    and external ad links (anikolsky.com, promokod.com, planetarium.ru,
    podushkin.ru) must be stripped when extracting the featured-docs list.
    Confine extraction to `<a href>` whose URL contains `vostlit.info/Texts/`.
12. **Featured-docs list on the homepage** uses `http://www.vostlit.info/...`
    (HTTP, not HTTPS; www) and sometimes malformed
    (`"https://www.vostlit.info/ http://www.vostlit.info/Texts/..."` — a
    space inside the href). The parser must tolerate and normalise these.
13. **Frameset pages (`frame*.htm`)** — structure not verified. The
    `primtext6.phtml` notes page declared a Frameset doctype but contained
    no `<frame>` elements and rendered normally. The `frame*.htm` files in
    the alpha index may or may not actually use frames. **Fetch one to
    confirm before writing the collector.**
14. **Some links cross regions.** The kavkaz catalog links to
    `../rus6/Pallas_2/text2.htm` (Pallas is filed under Russia, not
    Caucasus). The collector must follow cross-references and not assume
    region from path.

### 11.2 Unknowns (need verification)

- Structure of `otryv<M>.phtml` (excerpt) pages — assumed same as
  `document_text` `.phtml`, not fetched.
- Structure of `lit.phtml` (bibliography) pages — not fetched.
- Structure of `frame*.htm` (frameset) pages — not fetched.
- Structure of yearly `itogi<YY>.phtml?id=12320` pages — not fetched.
- Whether any document-text page embeds inline `<img>` scans — none seen
  in the sample, but the site has `.JPG` files so scans likely exist
  somewhere.
- Whether pre-reform Russian orthography (ѣ і ѳ ѵ) appears anywhere on the
  site — none found in the sample.
- Whether an on-site search exists — none found, but a `<form>` could be
  hidden in a page not fetched (e.g. a "Реперторий" sub-page).

---

## 12. Recommendations for the collector

1. **Decode before parse.** Always `raw.decode("windows-1251")` then
   `BeautifulSoup(text, "lxml")`. Never rely on auto-detection.
2. **Politeness.** 3–4 s between requests, max 3 retries with backoff,
   `User-Agent: Mozilla/5.0 (compatible; vostlit-research-audit/0.1)`.
   Respect 404/403/429 — stop on 403/429.
3. **Discovery order:**
   1. Fetch the homepage → get the 29 letter-index URLs + the documents-hub
      URL + the itogi URL.
   2. Fetch each of the 29 `haupt-Dateien/index-Dateien/<LETTER>.phtml?id=N`
      pages → enumerate all `/Texts/rus<N>/<slug>/` works and their part
      links.
   3. Fetch the documents hub → get the 45 `<region>.html` URLs.
   4. Fetch each `region.html` (especially `kavkaz.html`) → enumerate all
      `/Texts/Dokumenty/<region>/...` documents. **For Caucasus/Dagestan,
      `kavkaz.html` is the primary source.**
   5. Fetch each document-text page (`.phtml` or `.htm`) → extract body,
      citation, notes. For `.phtml` docs with notes links at the top
      (`primtext<M>.phtml`), fetch those too.
4. **Per-page extraction:**
   - Branch on URL suffix (`.phtml` vs `.htm`) and on presence of `#main`.
   - For `.phtml`: `#main` for body (exclude `#dann`), `#dann` for citation.
   - For `.htm`: whole `<body>` for body; find citation by
     `Текст воспроизведен по изданию:` regex (the block is in
     `<font color="#800040">`).
   - Footnote refs: collect all `<sup>` in body; record number + colour
     (`#0000FF` = footnote, none = also footnote; `#800000` = page break;
     `#FF0000` = source chapter).
5. **Work grouping.** Group part-pages by their directory prefix
   (`/Texts/rus<N>/<slug>/` or
   `/Texts/Dokumenty/<region>/<century>/<period>/<slug>/`). A "work" = all
   parts sharing that prefix. Use filename patterns (`text*`, `pred*`,
   `primtext*`, `lit*`, `karten*`, …) to classify parts.
6. **Store both identifiers.** For `.phtml` pages store `id` (numeric) AND
   full URL. For `.htm` pages store full URL only. Use full URL as the
   canonical primary key.
7. **Rate-limit / 404 handling.** Check `r.status_code == 200` before
   decoding as windows-1251 (404 bodies are `iso-8859-1`). Treat 404 as
   "page does not exist" (record and move on). Treat 403/429 as "stop and
   surface to operator".
8. **Test against the 13 saved fixtures** (§14) before running a full crawl.
   The fixtures cover every page type and both document flavors.

---

## 13. Appendix — full fetch log (reproducibility)

All fetches used `httpx` 0.28.1, `User-Agent: Mozilla/5.0 (compatible;
vostlit-research-audit/0.1)`, `follow_redirects=True`, `timeout=30 s`,
3.5 s sleep between requests. Europe/Moscow timezone.

| # | URL | HTTP | Content-Type | Bytes | Saved as fixture? |
|---|---|---|---|---|---|
| 1 | `https://www.vostlit.info/robots.txt` | 200 | `text/plain; charset=windows-1251` | (small) | No (text, not HTML) |
| 2 | `https://www.vostlit.info/` | 200 | `text/html; charset=WINDOWS-1251` | 123853 | **Yes** — `home.html` |
| 3 | `https://www.vostlit.info/common/itogi.phtml?id=101` | 200 | `text/html; charset=WINDOWS-1251` | 7942 | **Yes** — `itogi.html` |
| 4 | `https://www.vostlit.info/haupt-Dateien/index-Dateien/G.phtml?id=2044` | 200 | `text/html; charset=WINDOWS-1251` | 90854 | **Yes** — `alpha_index_G.html` |
| 5 | `https://www.vostlit.info/Texts/Dokumenty/index.phtml?id=2070` | 200 | `text/html; charset=WINDOWS-1251` | 15417 | **Yes** — `dokumenty_hub.html` |
| 6 | `https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577` | 200 | `text/html; charset=WINDOWS-1251` | 140260 | **Yes** — `document_text_iordan_text2.html` |
| 7 | `https://www.vostlit.info/Texts/rus13/Sirvan_Derbend/karten.phtml?id=1906` | 200 | `text/html; charset=WINDOWS-1251` | 6505 | **Yes** — `document_text_sirvan_derbend_karten.html` |
| 8 | `https://www.vostlit.info/Texts/rus5/Tunmann/pred.phtml?id=1541` | 200 | `text/html; charset=WINDOWS-1251` | 31432 | **Yes** — `document_text_tunmann_pred.html` |
| 9 | `https://www.vostlit.info/Texts/rus/Esai/pred2.phtml?id=483` | 200 | `text/html; charset=WINDOWS-1251` | 16480 | **Yes** — `document_text_esai_pred2.html` |
| 10 | `https://www.vostlit.info/Texts/rus6/Wachushti/text11.phtml?id=251` | 200 | `text/html; charset=WINDOWS-1251` | 84244 | **Yes** — `document_text_wachushti_text11.html` |
| 11 | `https://www.vostlit.info/Texts/Dokumenty/kavkaz.html` | 200 | `text/html; charset=WINDOWS-1251` | 750834 | **Yes (fragment)** — `kavkaz_catalog.fragment.html` (truncated to ~100 KB: head + table 0 + first 40 of 285 rows of table 1) |
| 12 | `https://www.vostlit.info/Texts/rus13/Sirvan_Derbend/text1.phtml?id=1906` | **404** | `text/html; charset=iso-8859-1` | 279 | No (deliberate 404 to test id-per-page hypothesis) |
| 13 | `https://www.vostlit.info/Texts/rus/Iordan/primtext6.phtml` | 200 | `text/html; charset=WINDOWS-1251` | 70697 | **Yes** — `notes_page_iordan_primtext6.html` |
| 14 | `https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm` | 200 | `text/html; charset=WINDOWS-1251` | 13834 | **Yes** — `document_text_dagestan_1792.html` |
| 15 | `https://www.vostlit.info/Texts/Dokumenty/Kavkaz/VI/Dag_chron/index.htm` | 200 | `text/html; charset=WINDOWS-1251` | 4572 | **Yes** — `document_text_dag_chron_index.html` |

**Totals:** 15 distinct URL fetches (14 × HTTP 200 + 1 × HTTP 404), all
`windows-1251` except the 404 body (`iso-8859-1`). 13 fixtures saved.

---

## 14. Test fixtures

Saved under `/home/z/my-project/vostlit-research/tests/fixtures/`:

- `fixtures_manifest.json` — authoritative manifest (filename, source_url,
  fetched_at, http_status, content_type, byte_size, sha256, encoding,
  description).
- `README.md` — provenance, encoding note, copyright notice.
- 13 HTML fixtures (listed in §13 above and in the manifest).

All fixtures are **raw server bytes** (windows-1251). Tests MUST decode
with `'windows-1251'` before parsing. The `kavkaz_catalog.fragment.html` is
a TRUNCATED snapshot (clearly marked in its HTML header comment and in the
manifest description) — do not parse it as a complete catalog.
