# Worked Example — The Mountain near Gumbet (Dagestan, 1839 map)

> This is a **real run** of the research algorithm against the seeded corpus
> (10 verified fixture pages + 5 curated entities). It is deliberately honest:
> it shows the pipeline succeeding on a query the corpus *can* answer, and
> honestly failing (with a concrete next step) on the specific question the
> corpus *cannot* yet answer. Nothing here is invented.

## The question

> «На карте 1839 года указано название горы или горного хребта в районе
> Гумбета, Дагестан. Установить точное прочтение названия и найти другие
> исторические упоминания.»

## Step 1 — Decompose

- **Entity sought**: a mountain/ridge name.
- **Geography**: Гумбет (historical society in Dagestan) and neighbours
  (Салатавия, Андийское общество, Авария).
- **Date**: the map is 1839; we want sources that could attest the name
  around or before that date.
- **Claim to test**: «the toponym on the 1839 map reads X, and X is attested
  in independent historical sources».

## Step 2 — Variant expansion

For the *geography* (to find documents that even mention the area):

- Гумбет, Гумбетъ, Гумбете
- Салатавия, Салатавія, Салатав
- Дагестан, Дагестанъ

For the *mountain generic* (the name on the map is unknown, so we search the
generic terms too): гора, хребет, перевал, вершина, высота, урочище, and the
Dagestani **меер**.

## Step 3 — Search ladder (actual CLI output)

```text
$ search-variants "Гумбет"
1 result — snippet "Гумбетъ" (normalised=гумбет; type=historical; status=candidate)
  → this is the CURATED variant, not a corpus attestation. status=candidate.

$ search-exact "Гумбет"
0 results   ← the word "Гумбет" does not appear in any imported body text

$ search-exact "Джалдари"
0 results   ← (illustrative candidate name; not in corpus)

$ search-fuzzy "Джалдари" --threshold 0.5
0 results

$ search-exact "гора"
3 results — BUT all in document 2 (Иордан, «Гетика»), about the Goths,
  not the Caucasus. → generic-term matches are NOISY; must filter by region.

$ by-region Кавказ
1 document (the Caucasus catalog fragment — a region_catalog, not a text)

$ mentions "Гумбет"
0 mentions
```

### Positive control — does the pipeline work at all?

To confirm the system returns real, verifiable fragments when the data *is*
present, I ran a query the corpus can answer:

```text
$ search-exact "дагестанск"
1 result — document 7, section 487
  snippet: "К вопросу о вхождении дагестанских владельцев в состав России. 1792 г."
  URL: https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm

$ context 487 --before 1 --after 1
  BEFORE (sec 486): "«ПРИНИМАТЬ ИХ ТАК, КАК ПОДДАННЫХ ЕЯ ИМПЕРАТОРСКОГО ВЕЛИЧЕСТВА»"
  SECTION (sec 487): "К вопросу о вхождении дагестанских владельцев в состав России. 1792 г."
  AFTER  (sec 488): "Вхождение Дагестана в состав России происходило непросто,
                     хотя отвечало чаяниям и населения, и высшей местной знати…"
```

This is a **verified** hit: real document, real section, real URL, original
orthography, with context. The pipeline is sound.

## Step 4 — Source criticism (for the positive control)

- **Document**: anon., «Принимать их так, как подданных ея императорского
  величества» — about Dagestan's entry into Russian subjection.
- **Document date**: 1792 (`original_creation_date`).
- **Edition**: Исторический архив, № 4. 2003 (`publication_year=2003`,
  `publication_title`).
- **Region tag**: Дагестан.
- It mentions "дагестанских владельцев" — so it is a relevant source for the
  *region*, but it does **not** mention Гумбет or any mountain name.

## Step 5 — Triangulation for the actual question

- No source in the corpus attests the name "Гумбет" in its body text.
- The only "Гумбет" record is the curated name-variant (status `candidate`),
  which is a *dictionary entry I created*, not a corpus attestation.
- No source attests "Джалдари" or any mountain-specific term in the Caucasus.

## Answer (required format)

### Краткий вывод
Прочтение названия горы/хребта near Гумбет на карте 1839 г. **не может быть
установлено** по текущему локальному корпусу: ни «Гумбет», ни вероятное
название «Джалдари-меер» не аттестованы в импортированных текстах. Корпус
на данный момент содержит 10 проверенных страниц, ни одна из которых не
является текстом по конкретной топонимике Гумбета.

### Найденные источники
- **[7]** (аноним) «Принимать их так, как подданных ея императорского
  величества». 1792. // Исторический архив, № 4. 2003.
  URL: https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm
  — релевантен *региону* (Дагестан), но не упоминает Гумбет или горные
  названия.

(Других источников по Гумбету в корпусе нет.)

### Дословные свидетельства
- **[7#487]** «К вопросу о вхождении дагестанских владельцев в состав
  России. 1792 г.» — подтверждает, что источник по Дагестану 1792 г.
  присутствует и доступен для проверки, но **не содержит** искомого
  топонима.

Свидетельств, прямо аттестующих название горы near Гумбет, **не найдено**.

### Анализ
Положительный контроль (запрос «дагестанск» → документ 7) доказывает, что
конвейер «парсер → FTS5 → контекст → цитата» работает и возвращает
проверяемые фрагменты. Отсутствие результатов по «Гумбет» и «Джалдари» —
следствие ограниченного корпуса, а не ошибки системы.

### Альтернативы и неопределённость
- Название на карте 1839 г. может быть записано в источниках, которые ещё
  не импортированы (каталог Кавказа, дагестанские хроники).
- «Джалдари-меер» — лишь один из возможных кандидатов; без карты и
  attestation в источниках отождествление невозможно.
- Не исключено, что одно название относилось к нескольким объектам.

### Итоговая оценка
**Не установлено.** Доказательств недостаточно. Это не означает, что
название не существовало, — лишь что корпус его не содержит.

### Следующие поисковые шаги
1. Расширить корпус краулингом каталога Кавказа и коллекции дагестанских
   хроник:
   ```
   python3 -m vostlit_research crawl --region caucasus --limit 25
   ```
   (первичные источники обнаружения — `/Texts/Dokumenty/kavkaz.html` и
   `/Texts/Dokumenty/Kavkaz/VI/Dag_chron/index.htm`, см. SITE_AUDIT.md §10).
2. После импорта повторить: `search-exact "Гумбет"`, `search-exact "меер"`,
   `search-fuzzy "Джалдари"`, `by-region Дагестан "гора"`.
3. Если название будет найдено — проверить дату источника отдельно от даты
   издания, прочитать контекст (`context <sec>`), и сопоставить с
   соседними обществами (Салатавия, Андийское).
4. Завести `name_variant` со статусом `candidate` только после того, как
   будет указан `evidence_section_id` из реального текста.

---

> **Methodological note.** This example is the *test of the algorithm*
> demanded by the master prompt (§11): it deliberately does NOT pre-record
> any specific mountain name as "the answer". The system's job is to report
> what the sources say — and, when they are silent, to say so and point to
> the concrete next search.
