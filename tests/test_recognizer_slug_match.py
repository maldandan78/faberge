"""Юнит-тесты сшивки ``title_en`` ML-индекса с нашим label_slug (контракт Faberge Search API 1.0.0).

Сервис поиска по фото отдаёт ``title_en`` — slug страницы предмета на сайте музея.
У большинства карточек наш label_slug ровно такой же, но не у всех: ключевые яйца
заведены с префиксом ``faberge_`` и подчёркиваниями, часть — другой транслитерацией
(``pasxalnoe_yajczo`` против ``paskhalnoe-yaytso``), длинные обрезаны до 100 знаков
с хвостом-хэшем. Slug'и ниже — реальные с прода (23.09.2026).

Запуск:
    python -m pytest tests/test_recognizer_slug_match.py
    python tests/test_recognizer_slug_match.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.recognizer import (  # noqa: E402
    build_slug_index,
    clamp_slug,
    match_slug,
    normalize_slug,
)

LONG_MUSEUM_SLUG = (
    "korobochka-s-emalevoj-miniatyuroj-vechernyaya-progulka-po-risunku-s-solomko-"
    "i-s-monogrammoj-velikoj-knyagini"
)
KNOWN = [
    "faberge_pasxalnoe_yajczo_buton_rozyi",
    "faberge_pasxalnoe_yajczo_chasyi_petushok",
    "faberge_paskhalnoye_yaytso_landyshi",
    "faberge_pasxalnoe_yajczo_kurochka",
    "blyudo-s-monogrammami-imperatora-nikolaya-ii-i-imperatritsy-aleksandry-fedorovny",
    "kovsh-odinnadtzataya-artel",
    "kovsh-prezentaczionnyij",
    "byuvar-s-monogrammami-imperatora-nikolaya-ii-i-imperatriczyi-aleksandryi-fedorovnyi",
    "czvetok-anyutinyi-glazki",
    "chasy",
    "chasy-2",
    "brooch",
    clamp_slug(LONG_MUSEUM_SLUG),
]
KNOWN_SET = set(KNOWN)
INDEX = build_slug_index(KNOWN)


def _match(title_en, cutoff=None):
    return match_slug(title_en, INDEX, KNOWN_SET, cutoff=cutoff)


def test_exact_slug():
    """Основной случай: title_en и есть наш label_slug."""
    assert _match("kovsh-odinnadtzataya-artel") == ("kovsh-odinnadtzataya-artel", "exact")
    assert _match("chasy-2") == ("chasy-2", "exact")
    assert _match("  brooch ") == ("brooch", "exact")


def test_long_slug_clamped_like_loader():
    """Slug длиннее 100 знаков у нас обрезан с хвостом-хэшем — сшиваем через тот же clamp."""
    assert len(LONG_MUSEUM_SLUG) > 100
    assert _match(LONG_MUSEUM_SLUG) == (clamp_slug(LONG_MUSEUM_SLUG), "exact")


def test_prefix_and_separators():
    """``faberge_…`` с подчёркиваниями — тот же предмет, что slug музея через дефисы."""
    assert _match("paskhalnoye-yaytso-landyshi") == ("faberge_paskhalnoye_yaytso_landyshi", "normalized")
    assert _match("PASKHALNOYE_YAYTSO_LANDYSHI") == ("faberge_paskhalnoye_yaytso_landyshi", "normalized")


def test_transliteration_variants():
    """Пример из контракта: paskhalnoe-yaytso-chasy-petushok ↔ pasxalnoe_yajczo_chasyi_petushok."""
    assert _match("paskhalnoe-yaytso-chasy-petushok") == (
        "faberge_pasxalnoe_yajczo_chasyi_petushok", "normalized",
    )
    assert _match("paskhalnoye-yaytso-kurochka") == ("faberge_pasxalnoe_yajczo_kurochka", "normalized")
    assert _match("paskhalnoe-yaytso-buton-rozy") == ("faberge_pasxalnoe_yajczo_buton_rozyi", "normalized")
    assert _match("tsvetok-anyutiny-glazki") == ("czvetok-anyutinyi-glazki", "normalized")
    assert _match("kovsh-odinnadtsataya-artel") == ("kovsh-odinnadtzataya-artel", "normalized")
    assert _match("kovsh-prezentatsionnyy") == ("kovsh-prezentaczionnyij", "normalized")


def test_fuzzy_small_difference():
    """Мелкое расхождение, которое свёртка не лечит, — нечётко."""
    slug, how = _match("blyudo-s-monogrammami-imperatora-nikolaya-ii-i-imperatritsy-aleksandry-feodorovny")
    assert slug == "blyudo-s-monogrammami-imperatora-nikolaya-ii-i-imperatritsy-aleksandry-fedorovny"
    assert how == "fuzzy"


def test_fuzzy_never_crosses_numbers():
    """chasy-3 — другой предмет, а не опечатка в chasy-2: номер различает одноимённые."""
    assert _match("chasy-3", cutoff=0.5) == (None, "miss")


def test_fuzzy_never_crosses_object_type():
    """Блюдо и бювар с одинаковым хвостом «с монограммами императора…» — разные предметы.

    Нашлось на слагах прода: без проверки первого слова ratio у пары ≈ 0.95.
    """
    rest = [s for s in KNOWN if not s.startswith("blyudo-")]
    slug, _ = match_slug(
        "blyudo-s-monogrammami-imperatora-nikolaya-ii-i-imperatritsy-aleksandry-fedorovny",
        build_slug_index(rest), set(rest), cutoff=0.5,
    )
    assert slug is None


def test_miss():
    assert _match("avtomobil-russo-balt") == (None, "miss")
    assert _match("") == (None, "miss")
    assert _match(None) == (None, "miss")


def test_fuzzy_disabled():
    slug, _ = _match(
        "blyudo-s-monogrammami-imperatora-nikolaya-ii-i-imperatritsy-aleksandry-feodorovny", cutoff=0,
    )
    assert slug is None


def test_normalize_slug():
    assert normalize_slug("faberge_pasxalnoe_yajczo_chasyi_petushok") == normalize_slug(
        "paskhalnoe-yaytso-chasy-petushok"
    )
    assert normalize_slug("--Chasy__2--") == "chasy-2"


def test_clamped_slugs_not_indexed_by_key():
    """Ключ обрезанного slug'а содержит хэш — в карту нормализованных ключей он не идёт."""
    assert clamp_slug(LONG_MUSEUM_SLUG) not in INDEX.values()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
