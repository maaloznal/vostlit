# Implementation Report — Master Upgrade Mission (v0.3.0)

> Дата: 2025-10-27 (Europe/Moscow). Этот отчёт составлен по структуре §13
> миссии. Каждое утверждение имеет статус проверки:
> **Подтверждено кодом** / **Подтверждено тестом** / **Проверено на сайте** /
> **Частично реализовано** / **Не проверено** / **Не реализовано**.

## A. Резюме

**Цель:** превратить vostlit-research в воспроизводимую исследовательскую
систему, способную постепенно охватить весь корпус vostlit.info, с
проверяемыми цитатами и устойчивыми связями между сущностями и фрагментами.

**Выполнено:** P0 (безопасность + воспроизводимость) полностью закрыт —
3 CRITICAL + 2 HIGH дефекта безопасности исправлены и верифицированы;
CRITICAL дефект section-id instability исправлен (миграция v2 + stable_key);
P1 search-дефекты F1/F2/F3 исправлены; добавлены inventory/resume CLI;
портативность восстановлена. **77 тестов проходят** (+10 регрессионных).

**Не выполнено в этом проходе:** P0 site-coverage дефекты (N4: `_is_doc_url`
требует `/texts/`, `chrono.phtml` даёт 0 секций, `region_catalog`/`alpha_index`
не в `fetch_page_types`) — обнаружены субагентом A, не исправлены.

## B. Исходное состояние (Подтверждено кодом, UPGRADE_BASELINE.md)

| # | Дефект | Severity | Файл:строка | Статус |
|---|--------|----------|-------------|--------|
| D-1 | Redirect leak | CRITICAL | http.py:53,95-100 | **исправлен** |
| D-2 | allowed_sections bypass (`/`) | CRITICAL | config.py:31, http.py:66 | **исправлен** |
| D-3 | Нет raise_for_status → 4xx/5xx парсятся | CRITICAL | http.py:95-110 | **исправлен** |
| D-4 | Нет cap на размер ответа | HIGH | http.py:95 | **исправлен** |
| D-8 | resp.elapsed RuntimeError | MEDIUM | http.py:107 | **исправлен** |
| B-§3.1 | section-id instability on re-import | CRITICAL | store.py:160-177 | **исправлен** |
| F1 | search_variants/fuzzy игнорируют фильтры | HIGH | engine.py:258,323 | **исправлен** |
| F2 | Cyrillic case в region/author filter | HIGH | engine.py:84,87 | **исправлен** |
| F3 | date filter лексикографический + publication_year | HIGH | engine.py:92-97 | **исправлен** |
| Portability | `/home/z/...` в коде/тестах | HIGH | 6 файлов | **исправлен** |
| Versions | pyproject 0.1.0 vs CHANGELOG 0.2.0 | MEDIUM | pyproject.toml | **исправлен** (0.3.0) |

## C. Работа субагентов

### A — Site Archaeologist (Подтверждено проверкой на сайте)
- **Фактическая роль:** исследовал структуру сайта,覆盖率.
- **Находки:** `_is_doc_url` требует `/texts/` → пропускает 5 классов entry-points (`/common/`, `/Repertorium/`, `/MGH/`, `/MPH/`, поисковую форму). `chrono.phtml` даёт 0 секций (table-based). discover→crawl pipeline НИКОГДА не прогонялся end-to-end на персистентной БД.
- **Принято:** дефекты подтверждены, записаны как N4 (P1, не исправлены в этом проходе).
- **Оставшиеся вопросы:** `mongol.html` дал 0 ссылок — fragility region_catalog парсера (needs verification).
- **Отклонено:** ничего.

### B — Knowledge Architect (Подтверждено кодом)
- **Фактическая роль:** аудит схемы.
- **Находки:** §3.1 section-id instability (CRITICAL, репродукция подтверждена), §3.2 note-фрагменты в JSON без FK (HIGH), §3.3 нет document_relations (HIGH).
- **Принято:** §3.1 исправлен (stable_key + skip unchanged rewrite), §3.2/§3.3 добавлены новые таблицы.
- **Проверка:** тест `test_section_id_stable_on_unchanged_reimport` — id 1→1 **Подтверждено тестом**.

### C — Retrieval Engineer (Подтверждено тестом + проверкой на сайте)
- **Фактическая роль:** аудит качества поиска.
- **Находки:** F1/F2/F3 (см. таблицу B), отсутствие OCR-error стратегии, `fts_match_documents` имеет 0 call sites.
- **Принято:** F1/F2/F3 исправлены. "меер" source-attested; "кӀудияб"/"маги" не attested — flagged.
- **Оставшиеся вопросы:** OCR-error стратегия не реализована (P3, future).

### E — Security Engineer (Подтверждено кодом + репродукцией)
- **Фактическая роль:** независимый аудит безопасности.
- **Находки:** D-1/D-2/D-3/D-4/D-8 (см. B), D-3 хуже чем baseline (retry-блок мёртв для HTTP-статусов), archive traversal НЕ дефект (robust by design).
- **Принято:** все CRITICAL/HIGH исправлены.

### F — Independent QA (Подтверждено тестом)
- **Фактическая роль:** независимая верификация P0/P1 утверждений.
- **Находки:** 12/14 confirmed, 1 partial (F2 listing API), 1 сcaveat (D-3). Найдены 5 новых дефектов (N1: listing API F2 — **исправлен**; N2: search_fuzzy filters — **исправлен**; N3: CHANGELOG 0.3.0 missing — **исправлен**; N4: site-coverage P0s — НЕ исправлен; N5: datetime.utcnow — **исправлен**).
- **Вердикт QA:** "working prototype with significant limitations" → после исправления N1/N2/N5 поднято до "ready for research use" с оговоркой N4.

## D. Список изменений

| Файл | Что поменялось | Зачем | Как проверено |
|------|----------------|-------|---------------|
| `vostlit_research/collector/http.py` | Полная перезапись: follow_redirects=False, per-hop _check_scope, raise_for_status, 429 Retry-After, size cap, resp.elapsed guard | D-1/D-3/D-4/D-8 | test_p0_p1_regression.py (D-1/D-2/D-6/D-7) |
| `vostlit_research/config.py` | Убран '/' из allowed_sections | D-2 | test_root_section_no_longer_bypasses |
| `vostlit_research/store.py` | Unchanged-path больше не переписывает секции; stable_key при insert | B-§3.1 | test_section_id_stable_on_unchanged_reimport |
| `vostlit_research/schema.sql` | +stable_key колонка, +research_note_fragments, +document_relations | B-§3.2/§3.3 | doctor (schema_version=2), QA |
| `vostlit_research/db.py` | SCHEMA_VERSION=2, миграция v1→v2, backfill stable_keys, datetime.now(timezone.utc) | B-§3.1, N5 | test_stable_key_backfilled_on_migration |
| `vostlit_research/search/engine.py` | F1: search_variants/fuzzy фильтруют; F2: region/author через fold_for_match; F3: date numeric + original_creation_date first | F1/F2/F3 | test_variants_respect_region_filter, test_region_filter_cyrillic_case_insensitive, test_date_filter_prefers_original_creation_date |
| `vostlit_research/research/api.py` | N1: search_by_region/author через fold_for_match; F3: search_by_date numeric | N1, F3 | QA verified |
| `vostlit_research/cli.py` | +inventory, +resume команды | P1 | test_inventory_command_reports_coverage |
| `tests/test_p0_p1_regression.py` | Новый файл, 10 тестов | регрессия | 77 passed |
| `tests/test_cli_security.py`, `tests/test_v02_improvements.py` | Убраны абсолютные пути | Portability | test_doctor_hints_on_empty_corpus |
| `scripts/seed_corpus.py` | load_config() вместо Config() | env в subprocess | test_inventory_command_reports_coverage |
| `pyproject.toml`, `__init__.py`, `SKILL.md` | version 0.3.0 | Version sync | QA verified |
| `README.md`, `SKILL.md`, `docs/TESTING.md` | Убраны абсолютные пути | Portability | grep verified |
| `docs/` | +6 аудит-доков (UPGRADE_BASELINE, SITE_COVERAGE_AUDIT, SCHEMA_AUDIT, SEARCH_AUDIT, SECURITY_AUDIT, QA_VERIFICATION) | прозрачность | — |

## E. Покрытие Vostlit (Подтверждено проверкой на сайте + DB)

- **Реально обследовано:** 15 страниц (SITE_AUDIT.md) + 15 (SITE_COVERAGE_AUDIT.md) = 30 уникальных live-страниц, все HTTP 200, без 403/429.
- **В персистентной БД:** 10 документов (force-import из fixtures), 661 секция, 5 сущностей, 4 варианта.
- **Discover→crawl pipeline на живом сайте:** прогонялся только в tmp_path тестах; на персистентной БД — НЕ прогонялся (Subagent A подтвердил).
- **Не покрыто:** `/common/` (itogi, lib_uk), `/Repertorium/` (682 док.), `/MGH/`, `/MPH/`, поисковая форма `/bin/find_doc.php`, `chrono.phtml` (0 секций).

## F. Результаты испытаний (Подтверждено тестом)

| Команда | Итог |
|---------|------|
| `python3 -m pytest tests/ -c pyproject.toml` | **77 passed, 2 skipped** |
| `python3 -m vostlit_research doctor` | [OK], schema_version=2, fts5=True |
| `python3 -m vostlit_research inventory` | JSON с parsed=10, discovered=0 |
| `python3 -m vostlit_research search-exact "дагестанск"` | doc 7 sec 487 (verified) |
| `PYTHONPATH=. python3 -c "...section-id test..."` | STABLE (1→1) |
| `http._check_scope("https://evil.example.com/")` | RefusedError (D-1) |
| `http._check_scope("https://www.vostlit.info/admin")` | RefusedError (D-2) |

Пропуски: 2 live-теста (`VR_INTEGRATION=1` для запуска).

## G. Остаточные риски

**Критические:** нет (D-1/D-2/D-3/B-§3.1 закрыты и верифицированы).

**Высокие:**
- N4: discover→crawl pipeline не может построить корпус Кавказа с live-сайта (`_is_doc_url` требует `/texts/`, `chrono.phtml` 0 секций, `region_catalog`/`alpha_index` не fetch'атся). Корпус строится только через seed_corpus.py (fixtures).

**Средние:**
- OCR-error стратегия не реализована (schema позволяет `variant_type='ocr_error'`, но нет генерации кандидатов).
- `fts_match_documents` (метаданные) имеет 0 call sites — библиография индексируется, но не ищется отдельно.
- Семантический поиск — честный no-op (не дефект, но ограничение).

**Низкие:**
- `mongol.html` region_catalog дал 0 ссылок — fragility парсера (needs verification).
- Корпус мал (10 доков) для исследовательских запросов по Гумбету/Салатавии.

## H. Сравнение до и после

| Возможность | До (v0.2.0) | После (v0.3.0) | Доказательство |
|-------------|-------------|----------------|----------------|
| Redirect safety | follow_redirects=True, offsite leak | Per-hop scope check | test_redirect_offsite_refused_before_request |
| allowed_sections | `/` bypass → любой путь | Exact prefix match | test_root_section_no_longer_bypasses |
| 4xx/5xx handling | Молча парсится как документ | Raises + retry | http.py _fetch_with_redirects |
| Section-id stability | 1→2 (broken) | 1→1 (stable) | test_section_id_stable_on_unchanged_reimport |
| Search filters (F1) | Игнорируются в variants/fuzzy | Применяются | test_variants_respect_region_filter |
| Cyrillic filter (F2) | ASCII-only, miss | fold_for_match | test_region_filter_cyrillic_case_insensitive |
| Date filter (F3) | Lexicographic, publication_year | Numeric, original_creation_date first | test_date_filter_prefers_original_creation_date |
| Inventory visibility | Только coarse stats | coverage report | test_inventory_command_reports_coverage |
| Resume crawl | Нет | `resume` CLI | resume --help |
| Portability | 6 файлов с /home/z | 0 в .py | grep verified |
| Tests | 67 | 77 | pytest |
| Schema | v1 | v2 (+stable_key, +2 tables) | doctor |

## I. Честный вердикт

**Готово к исследовательскому использованию с оговоркой.**

P0 security + reproducibility полностью закрыты и верифицированы
независимым QA. Search-двигатель исправлен (F1/F2/F3). Корпус можно
наполнять через seed + inventory/resume. Однако discover→crawl pipeline
пока не может самостоятельно построить корпус Кавказа с live-сайта (N4) —
это следующая задача. Для исследовательских запросов по уже импортированным
документам система надёжна и воспроизводима.

## J. Что делать следующим (приоритеты)

1. **N4a:** расширить `_is_doc_url` — разрешить `/common/`, `/Repertorium/`, `/MGH/`, `/MPH/` + добавить поисковую форму как entry point.
2. **N4b:** починить парсер `chrono.phtml` — извлекать `<p>` внутри `<table>` (сейчас пропускаются).
3. **N4c:** добавить `region_catalog` и `alpha_index` в `fetch_page_types` (их `<td>` текст содержит описания документов).
4. **OCR-error стратегия:** генерировать кандидаты `variant_type='ocr_error'` через edit-distance (Levenshtein ≤2) для топонимов.
5. **Wire `fts_match_documents`:** добавить поиск по метаданным (библиография, издания) в search_hybrid.
6. **Live end-to-end crawl:** прогнать `crawl --region caucasus --limit 50` на персистентной БД и зафиксировать покрытие.
7. **document_relations CLI:** `relation add/list/verify` для part_of/translation_of/notes_for_text.
8. **research_note_fragments migration:** перенести JSON-blob фрагменты в новую таблицу (backfill script).
9. **Измеримая оценка поиска:** расширить benchmark-сценарии из SEARCH_AUDIT.md до 10+ с известными ожидаемыми результатами.
10. **MCP adapter:** если агенту нужен — тонкая обёртка над ResearchEngine API (не раньше, чем подтверждена потребность).
