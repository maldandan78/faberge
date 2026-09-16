"""Следующие по вероятности варианты доезжают до ответа (запрос музея 16.09.2026).

Модель отдаёт не один ответ, а ранжированный список. До правки ML-сервис
спрашивали с `limit = top_k`, а полученные предсказания потом ещё и схлопывали
(несколько ракурсов одного предмета → один slug) и отбрасывали (название не
сшилось с каталогом) — поэтому при top_k=3 до фронта доезжал ОДИН вариант.
Проверено на проде 16.09.2026 на фото «Часы Петушок»: limit=3 → 1 кандидат,
limit=10 → 4. Здесь это закреплено тестом.

БД и сеть не нужны: httpx.AsyncClient подменяется заглушкой. Запуск:
    python -m pytest tests/test_recognition_alternatives.py
    python tests/test_recognition_alternatives.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.services import recognizer  # noqa: E402

CATALOG = {
    "Часы «Петушок»": "clock_rooster",
    "Яйцо «Шантеклер»": "egg_chanticleer",
    "Яйцо «Орден Святого Георгия»": "egg_george",
    "Яйцо герцогини Мальборо": "egg_marlborough",
}
KNOWN = list(CATALOG.values())


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Заглушка httpx.AsyncClient: запоминает отправленный `limit`."""

    def __init__(self, predictions, sent):
        self._predictions = predictions
        self._sent = sent

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, files=None, data=None):
        self._sent.append(data or {})
        return _FakeResponse({"predictions": self._predictions, "found": True})


def _search(predictions, top_k=3):
    """Прогнать реальную ветку распознавания на подставленных предсказаниях."""
    sent: list[dict] = []
    original = recognizer.httpx.AsyncClient
    recognizer.httpx.AsyncClient = _FakeClient(predictions, sent)
    try:
        outcome = asyncio.run(
            recognizer._recognize_search(b"photo", CATALOG, KNOWN, top_k)
        )
    finally:
        recognizer.httpx.AsyncClient = original
    return outcome, sent


def test_ml_service_is_asked_with_headroom():
    """ML просим с запасом, а не ровно top_k — иначе дедуп съедает варианты."""
    _, sent = _search([{"item_id": 1, "title": "Часы «Петушок»", "confidence": 0.93}], top_k=3)
    assert sent and int(sent[0]["limit"]) == settings.recognition_search_limit
    assert int(sent[0]["limit"]) > 3


def test_top_k_is_respected_for_larger_requests():
    """Если попросили больше запаса — отдаём столько, сколько попросили."""
    _, sent = _search([{"item_id": 1, "title": "Часы «Петушок»", "confidence": 0.93}], top_k=50)
    assert int(sent[0]["limit"]) == 50


def test_recognized_answer_keeps_next_by_probability():
    """Уверенный ответ НЕ обрезает список: первым — найденный, дальше — варианты."""
    outcome, _ = _search([
        {"item_id": 1, "title": "Часы «Петушок»", "confidence": 0.93},
        {"item_id": 2, "title": "Яйцо «Шантеклер»", "confidence": 0.66},
        {"item_id": 3, "title": "Яйцо «Орден Святого Георгия»", "confidence": 0.63},
    ], top_k=3)
    assert outcome.recognized is True
    assert outcome.label_slug == "clock_rooster"
    assert [slug for slug, _ in outcome.candidates] == [
        "clock_rooster", "egg_chanticleer", "egg_george",
    ]
    # Порядок — по убыванию уверенности, как их ранжировала модель.
    confidences = [conf for _, conf in outcome.candidates]
    assert confidences == sorted(confidences, reverse=True)


def test_duplicate_shots_of_one_item_do_not_eat_slots():
    """Несколько ракурсов одного предмета — один кандидат, остальные слоты живые.

    Ровно это и ломало выдачу на проде: индекс ML ключуется по снимкам, и при
    limit=3 все три верхние строки оказывались одним и тем же яйцом.
    """
    outcome, _ = _search([
        {"item_id": 1, "title": "Часы «Петушок»", "confidence": 0.93},
        {"item_id": 2, "title": "часы петушок", "confidence": 0.91},     # тот же предмет
        {"item_id": 3, "title": "Часы «Петушок».", "confidence": 0.88},  # и снова он
        {"item_id": 4, "title": "Яйцо «Шантеклер»", "confidence": 0.66},
        {"item_id": 5, "title": "Яйцо герцогини Мальборо", "confidence": 0.60},
    ], top_k=3)
    assert [slug for slug, _ in outcome.candidates] == [
        "clock_rooster", "egg_chanticleer", "egg_marlborough",
    ]


def test_unmatched_titles_do_not_eat_slots():
    """Название, не сшитое с каталогом, не занимает место живого варианта."""
    outcome, _ = _search([
        {"item_id": 1, "title": "Часы «Петушок»", "confidence": 0.93},
        {"item_id": 2, "title": "Автомобиль Руссо-Балт", "confidence": 0.70},
        {"item_id": 3, "title": "Яйцо «Шантеклер»", "confidence": 0.66},
        {"item_id": 4, "title": "Яйцо герцогини Мальборо", "confidence": 0.60},
    ], top_k=3)
    assert [slug for slug, _ in outcome.candidates] == [
        "clock_rooster", "egg_chanticleer", "egg_marlborough",
    ]
    assert outcome.unmatched == [("Автомобиль Руссо-Балт", 0.70)]


def test_stub_also_returns_alternatives_when_recognized():
    """Стаб повторяет форму реального ответа — экран отлаживается без ML."""
    known = ["a", "b", "c", "d"]
    recognized = []
    for payload in (b"one", b"two", b"three", b"four", b"five", b"six"):
        outcome = recognizer._recognize_stub(payload, known, top_k=3)
        if outcome.recognized:
            recognized.append(outcome)
            assert outcome.candidates[0][0] == outcome.label_slug
            assert len(outcome.candidates) == 3
    assert recognized, "ни один снимок не прошёл порог — тест ничего не проверил"


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
