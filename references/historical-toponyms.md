# Historical Toponyms & Name Variants

How the system handles the many spellings a single historical place can have
across the vostlit.info corpus. This is the operational detail behind master
prompt §7.

## 1. The four representations

For every attested name the system keeps FOUR separate views; it never
collapses them silently:

1. **Original form** (`name_variants.original_form`) — exactly as printed,
   including pre-reform letters and OCR artifacts. e.g. `Гумбетъ`, `Салатавія`.
2. **Normalised form** (`normalized_form`) — `normalise_search()` output:
   lowercased, ѣ→е, і→и, ѳ→ф, ѵ→и, ё→е, ъ dropped, punctuation→space. Used
   for FTS5 indexing and exact-match comparison. e.g. `гумбет`, `салатавия`.
3. **Core toponym** (`strip_geo_generic()`) — the generic geographic terms
   removed (гора, хребет, перевал, вершина, высота, урочище, ущелье, долина,
   аул, кишлак, and the Dagestani **меер**, plus Latin/German/French
   generics berg/pass/mont/…). Used for fuzzy core-matching. e.g.
   `гора Джалдари-меер` → `джалдари`.
4. **Canonical entity** (`entities.canonical_name`) — the single identity the
   variants point to, with a `verification_status`. Linking a variant to an
   entity is a *claim* that must be evidenced, not a string-comparison
   automatisation.

## 2. Generic geographic terms (for mountain search)

When searching for a mountain/ridge, do NOT rely on the word «гора» alone.
The corpus uses many equivalents; `strip_geo_generic` removes all of these:

- Russian: гора, хребет, перевал, вершина, высота, урочище, ущелье, долина,
  крепость, башня, аул, кишлак, село, деревня.
- Dagestani/Caucasian: **меер** (mountain/peak — appears in names like
  Джалдари-меер).
- Latin/German/French/English: berg, gebirge, pass, mont, montagne, mount,
  mt/m., height, ridge, peak.

So `search-exact "Джалдари-меер"` AND `search-exact "Джалдари"` AND
`search-fuzzy "Джалдари"` are all worth running.

## 3. Pre-reform / modern equivalence

`normalise_search` folds the pre-reform letters:

| Pre-reform | Modern |
|------------|--------|
| ѣ | е |
| і | и |
| ѳ | ф |
| ѵ | и |
| ъ (final) | (dropped) |
| ё | е |

So searching `Салатавія` finds `Салатавия` and vice versa. The original
spelling is always preserved in `original_form` / `text`.

## 4. Variant workflow

```
user name
   │
   ├─ search-variants "<name>"        # dictionary lookup (original + normalised + FTS)
   ├─ search-fuzzy    "<core>"        # candidate entities/variants, similarity-scored
   ├─ for each candidate:
   │     check evidence_section_id    # WHERE is this spelling attested?
   │     check verification_status    # confirmed / candidate / rejected
   │     read context                 # does the context match the geography+date?
   └─ only then link to canonical entity (and even then, mark confidence)
```

## 5. Common Dagestan/Caucasus toponym families (illustrative, NOT a lookup table)

These are families of spellings you may encounter; the system does NOT
pre-merge them — you must verify each:

- **Гумбет** — Гумбетъ, Гумбете, Humbeit (German).
- **Салатавия** — Салатавія, Салатав, Salatawia.
- **Авария** — Аварія, Авар, Awar.
- **Дербент** — Дербенд, Дарбанд, Derbend, Derbent.
- **Эндирей** — Андреева, Ендери, Endirey.

> ⚠️ The above are examples of the *kind* of variation that exists, drawn from
> the scholarly literature. Do NOT treat them as confirmed attestations in the
> corpus — verify each with `search-variants` before citing.

## 6. What the system will NOT do

- It will never auto-merge two toponyms because they look alike.
- It will never promote a `candidate` variant to `confirmed` without an
  explicit human/agent action (and that action is logged).
- It will never return a fake semantic match; if no embedding model is
  configured, semantic search contributes zero results.
