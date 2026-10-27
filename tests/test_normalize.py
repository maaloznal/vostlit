"""Normalisation & fuzzy matching tests (master prompt §7, §15)."""
from __future__ import annotations

from vostlit_research import textnorm


def test_lower_cyr_handles_cyrillic():
    assert textnorm.lower_cyr("ГУМБЕТ") == "гумбет"
    assert textnorm.lower_cyr("Салатавія") == "салатавія"


def test_normalise_search_folds_prereform_and_yo():
    # ѣ -> е, і -> и, ѳ -> ф, ё -> е, case-fold, punct stripped
    assert textnorm.normalise_search("Гумбетъ") == "гумбет"  # ъ dropped
    assert textnorm.normalise_search("Салатавія") == "салатавия"
    assert textnorm.normalise_search("Ёлка, ѣсть, і") == "елка есть и"
    assert textnorm.normalise_search("Гора  Джалдари-меер!") == "гора джалдари меер"


def test_original_not_destroyed():
    # the function returns a new string; original is untouched
    s = "Гумбетъ, Салатавія"
    _ = textnorm.normalise_search(s)
    assert s == "Гумбетъ, Салатавія"


def test_normalise_url_keeps_id_drops_fragment():
    u = "https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577#note"
    assert textnorm.normalise_url(u) == "https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577"


def test_normalise_url_normalises_host_scheme():
    u = "HTTP://VostLit.info/Texts/rus/Iordan/text2.phtml?id=577&x=1"
    assert textnorm.normalise_url(u) == "https://vostlit.info/Texts/rus/Iordan/text2.phtml?id=577"


def test_normalise_url_strips_trailing_slash():
    assert textnorm.normalise_url("https://www.vostlit.info/Texts/Dokumenty/kavkaz.html/") == \
        "https://www.vostlit.info/Texts/Dokumenty/kavkaz.html"


def test_stable_id_from_url():
    assert textnorm.stable_id_from_url("https://www.vostlit.info/Texts/rus/Iordan/text2.phtml?id=577") == "577"
    # bare .htm: no id -> path used
    assert textnorm.stable_id_from_url("https://www.vostlit.info/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm") == \
        "/Texts/Dokumenty/Kavkaz/XVIII/1780-1800/Dagestan_poddanstvo_1792/text.htm"


def test_similarity_and_fuzzy_candidates():
    cands = [("Джалдари-меер", 1), ("Джалдары-меер", 2), ("Гумбет", 3), ("Москва", 4)]
    res = textnorm.fuzzy_candidates("Джалдари-меер", cands, threshold=0.6)
    assert res[0][1] in (1, 2)
    assert all(score < 0.6 for score, _ in res if _ in (3, 4)) or all(_ in (1, 2) for _, _ in res)


def test_strip_geo_generic_removes_mountain_terms():
    # "меер" is itself a Dagestani generic for "mountain", so it is stripped
    # too — leaving the toponym core "джалдари" for fuzzy matching.
    assert textnorm.strip_geo_generic("гора Джалдари-меер") == "джалдари"
    assert textnorm.strip_geo_generic("хребет Гумбет") == "гумбет"
    assert textnorm.strip_geo_generic("Mont Blanc") == "blanc"


def test_build_fts_query_phrases_and_yo():
    assert textnorm.build_fts_query("гумбет") in ("гумбет", "(гумбет OR гумбете)")
    # multiword -> quoted phrase, special chars stripped
    q = textnorm.build_fts_query('гумбет "тест" (foo)')
    assert q.startswith('"') and q.endswith('"')
    assert '"' not in q[1:-1]


def test_has_pre_reform():
    assert textnorm.has_pre_reform("Салатавія")
    assert not textnorm.has_pre_reform("Салатавия")


def test_fold_for_match_preserves_length():
    # 1:1 char map -> same length (so offsets map back to original)
    s = "Гумбетъ Ёлка ѣсть"
    assert len(textnorm.fold_for_match(s)) == len(s)
