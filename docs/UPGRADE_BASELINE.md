# UPGRADE BASELINE — реальное состояние до апгрейда

> Дата: 2025-10-27 (Europe/Moscow). Этот документ фиксирует **фактически
> проверенное** состояние репозитория `maaloznal/vostlit` на коммите
> `42865f7` (v0.2.0 по CHANGELOG) перед началом работ по Master Upgrade
> Mission. Каждое утверждение имеет статус проверки.

## A. Структура проекта (Подтверждено кодом)

```
vostlit-research/
├── vostlit_research/          # пакет (15 модулей)
│   ├── collector/ {http,parser,discover,crawl}.py
│   ├── search/ {fts,engine,semantic}.py
│   ├── research/ api.py
│   ├── {config,db,models,textnorm,store,archive,io,cli}.py + schema.sql
├── tests/ (6 файлов + 13 фикстур)
├── docs/ (7 файлов)
├── scripts/ (5 файлов)
├── SKILL.md, README.md, CHANGELOG.md, pyproject.toml
```

## B. Контрольные точки (Фаза I, §3 миссии)

### 1. Портативность — НЕ ПРОЙДЕНО
**Подтверждено кодом:** 6 файлов содержат жёстко заданный абсолютный путь
`/home/z/my-project/vostlit-research`:
- `README.md:36`, `SKILL.md:45,52`
- `tests/test_v02_improvements.py:247,250` (PYTHONPATH + cwd в тесте doctor)
- `tests/test_cli_security.py:14` (ROOT-константа)
- `docs/SITE_AUDIT.md:885`, `docs/TESTING.md:6`

Тест `test_doctor_hints_on_empty_corpus` падает при запуске из другого
каталога, т.к. использует абсолютный `PYTHONPATH` и `cwd`.

### 2. Сетевой клиент: проверка URL до каждого запроса — НЕ ПРОЙДЕНО (критично)
**Подтверждено кодом** (`vostlit_research/collector/http.py:53-100`):
- `httpx.Client(follow_redirects=True)` — редиректы следуются автоматически
  в одном вызове `client.get()`.
- `_check_scope()` проверяет только **начальный** URL.
- Проверка `final_host` делается **после** `resp = client.get()` — т.е.
  после того, как запрос уже ушёл на чужой домен (утечка User-Agent, headers).
- Промежуточные хопы редиректа вообще не проверяются.

**Доказательство:** скрипт подтвердил, что при `follow_redirects=True` httpx
выполняет всю цепочку в одном `.get()`, и `final_host`-проверка срабатывает
только post-factum.

### 3. `allowed_sections` — НЕ ПРОЙДЕНО (критично)
**Подтверждено кодом** (`config.py` default + `http.py:60-69`):
- `allowed_sections = ('/', '/haupt-Dateien/', '/Texts/', '/common/')`
- Проверка: `any(path.startswith(sec) for sec in allowed_sections)`
- Поскольку `'/' in allowed_sections` и **любой** абсолютный путь начинается
  с `/`, условие **всегда True** — ограничение фактически не работает.
- Скрипт подтвердил: пути `/admin`, `/secret`, `/anything/at/all` все
  проходят проверку.

### 4. Версии — НЕ СОГЛАСОВАНО
- `pyproject.toml`: `version = "0.1.0"`
- `vostlit_research/__init__.py`: `__version__ = "0.1.0"`
- `CHANGELOG.md`: последняя запись `[0.2.0]`
- `SKILL.md`: `version: 0.1.0` в frontmatter

→ Код и CHANGELOG рассогласованы (v0.1.0 vs v0.2.0).

### 5. Число тестов — Подтверждено тестом
`python3 -m pytest tests/ -c pyproject.toml` → **67 passed, 2 skipped**
(2 — live-интеграционные, отключены по умолчанию).

### 6. Соответствие описания и кода — Частично
- CLI-команды в README/SKILL соответствуют реализованным в `cli.py`.
- Документация SITE_AUDIT.md соответствует фиксурам.
- Но: README/SKILL содержат абсолютные пути (дефект №1).

### 7. Актуальность аудита сайта — Подтверждено
`docs/SITE_AUDIT.md` основан на 15 реально fetched страницах; фикстуры
совпадают (sha256 в манифесте). Frameset-страницы добавлены в v0.2.0.

### 8. Парсер на всех фикстурах — Подтверждено тестом
`tests/test_parser.py` — 13 тестов покрывают все 13 фикстур, все проходят.

### 9. Покрытие типов страниц — Частично
Обнаруженные, но **пропускаемые** сборщиком типы: `home`, `alpha_index`,
`documents_hub`, `region_catalog`, `itogi_index` (не входят в
`fetch_page_types`). Это намеренно (они индексные), но `region_catalog`
и `alpha_index` содержат полезный текст, который сейчас не индексируется.

### 10. Видимость инвентаря — НЕ ПРОЙДЕНО
- `stats` даёт только грубые счётчики (documents_by_status, by_type).
- **Нет** команды `inventory` / `coverage` / `resume` / `queue`.
- Невозможно увидеть: что обнаружено, но не загружено; что давно не
  проверялось; какие ошибки требуют повторной обработки.
- `crawl_log` существует, но без агрегирующих запросов/CLI.

## C. Дополнительные подтверждённые дефекты

- **429 без Retry-After:** `http.py` обрабатывает 429 как обычную
  `HTTPError` — ретраит с backoff, но не уважает заголовок `Retry-After`.
- **Нет cap на размер ответа:** `resp.content` грузится целиком в память;
  злонамеренно большая страница может исчерпать память.
- **`extract-mentions` не вызывается автоматически** после crawl —
  пользователь должен запустить отдельно.
- **Связи между произведениями** основаны ТОЛЬКО на общем URL-префиксе
  (`_work_prefix`); нет отдельной таблицы связей с типом и доказательством.
- **Семантический поиск** — честный no-op (не дефект, но документация
  должна это явно подчёркивать).

## D. Что работает (Подтверждено)

- SQLite + FTS5 bootstrap, миграции (`schema_version`).
- Парсер: 9 типов страниц, windows-1251, frameset, цитаты, сноски.
- Дедупликация по canonical_url, версионирование по content_hash.
- Поиск: exact (Cyrillic-aware), FTS5 (pre-reform/ё-insensitive),
  variant, fuzzy (candidates only), hybrid, toponym (§11).
- Research engine: get_document, context, mentions, compare_sources,
  extract_mentions, search_toponym.
- CLI: 22 команды.
- 67 тестов проходят.

## E. Приоритеты P0 (должны быть исправлены до массового сбора)

1. **Дефект A (редиректы):** отключить `follow_redirects`, обрабатывать
   каждый редирект вручную с `_check_scope` на каждом хопе. + регресс-тест.
2. **Дефект B (allowed_sections):** убрать `/` из default; проверять
   точное начало пути против явных префиксов; + тесты на запрещённые пути.
3. **Дефект D (портативность):** заменить абсолютные пути на
   `Path(__file__).resolve().parent.parent` / `cwd=ROOT`.
4. **429 + Retry-After:** уважать заголовок; + cap на размер ответа.
5. **Версии:** синхронизировать pyproject/SKILL/__init__/CHANGELOG.
