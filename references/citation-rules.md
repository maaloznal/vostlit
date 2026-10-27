# Citation Rules

How to cite a fragment from the vostlit-research corpus so a reader (or
another agent) can verify it.

## 1. Minimum citation

Every claim must cite, at minimum:

- the **document title** (and author if present),
- the **document date** (the source's date, not the edition's),
- the **canonical URL** on vostlit.info,
- the **`document_id`** and **`section_id`** from the local DB,
- the **edition** (`publication_title`).

## 2. Template

```
[<document_id>#<section_id>] <Author>. <Title>. <document date>.
Текст воспроизведен по изданию: <publication_title>.
URL: <canonical_url>
```

Example (from the seeded corpus):

```
[7#487] (аноним) «Принимать их так, как подданных ея императорского
величества». 1792.
Текст воспроизведен по изданию: «Принимать их так, как подданных ея
императорского величества». К вопросу о вхождении дагестанских владельцев
в состав России. 1792 г. // Исторический архив, № 4. 2003
URL: https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm
```

## 3. Quoting

- Quote the **`text` of the section** verbatim, in its original orthography
  (including pre-reform letters).
- If you trim a quote, mark the cut with `[…]`.
- If the text is OCR-sourced and you suspect errors, append `(OCR, не
  выверено)`.
- Never rephrase a quote and present it as verbatim.

## 4. Distinguishing testimony from commentary

- A quote from a `body` section is **source testimony**.
- A quote from a `note` section is the **editor's commentary** — cite it as
  such: `(комментарий издателя: …)`.
- A quote from a `bibliography` section is the **edition citation**, not the
  source's own words.

## 5. When you used context

If your reading depends on the surrounding sections (e.g. the name is
disambiguated by a clause two sections earlier), cite those too:

```
see also [7#486] for the geographic context that disambiguates the mention.
```

## 6. Reproducibility

A second agent running `context <section_id>` must see the same text. If the
corpus has been re-crawled and a new `document_versions` row was created, the
old version is retained — cite the `content_hash` if precision matters:

```
version content_hash=<sha256>, parser <parser_version>
```

## 7. What is NOT a citation

- "According to vostlit.info…" with no URL or section.
- A paraphrase with no verbatim quote.
- A fuzzy-match candidate presented as the source's wording.
- A URL you did not fetch (the URL must be a `canonical_url` actually present
  in the `documents` table).
