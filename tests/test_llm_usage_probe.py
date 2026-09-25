"""Юнит-тесты замера расхода LLM/SpeechKit (``scripts/measure_llm_usage.py``, запрос 02.09.2026).

Скрипт считает цифры, которые уезжают в переписку («медиана input на рассказ —
столько-то»), поэтому под ними должен быть тест, а не «я запускал, было похоже».
Проверяется ровно то, где можно ошибиться молча:

  1. разбор строки расхода — и «голой», и внутри JSON-обёртки Cloud Logging
     (последнее поле там приезжает как ``total_tokens=592","stream":…``);
  2. формат не разъехался с приложением: строка берётся не из константы теста,
     а из настоящего ``llm._log_usage``; для ``tts_request`` — гвардия по полям;
  3. медианы по операциям и медиана «на одного посетителя» (сумма по экспонату,
     потом медиана по экспонатам, а не медиана медиан);
  4. привязка вызова к экспонату и шагу сценария, включая упавший шаг: 502 после
     ответа модели уже оплачен и обязан попасть в сводку.

Сеть и БД не нужны.

    python -m pytest tests/test_llm_usage_probe.py
    python tests/test_llm_usage_probe.py          # standalone
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import measure_llm_usage as probe  # noqa: E402

from app import schemas as sch  # noqa: E402
from app.config import settings  # noqa: E402
from app.services import llm  # noqa: E402


PLAIN = (
    "2026-09-01T10:00:01Z INFO app.services.llm llm_usage operation=story "
    "model=gpt://b1g/yandexgpt/latest model_version=23.10.2024 "
    "input_tokens=612 output_tokens=280 total_tokens=892"
)
WRAPPED = (
    '{"level":"INFO","message":"llm_usage operation=chat model=gpt://b1g/yandexgpt/latest '
    'model_version=23.10.2024 input_tokens=402 output_tokens=170 total_tokens=572","stream":"stderr"}'
)
TTS_WRAPPED = (
    '{"message":"tts_request api=v3 voice=alena role=good fmt=mp3 '
    'chars=884 duration_ms=59040 bytes=176032"}'
)


@contextlib.contextmanager
def collector_attached():
    """Обработчик на корневом логгере — как в ``run_live``."""
    handler = probe.UsageCollector()
    root = logging.getLogger()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


def _call(operation: str, **kwargs) -> probe.Usage:
    return probe.Usage(kind="llm", operation=operation, **kwargs)


# ── 1. Разбор строк ──────────────────────────────────────────────────────────
def test_parses_plain_line():
    usage = probe.parse_usage_line(PLAIN)
    assert usage is not None
    assert (usage.kind, usage.operation) == ("llm", "story")
    assert usage.model == "gpt://b1g/yandexgpt/latest", "URI модели не должен обрезаться по '/'"
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (612, 280, 892)


def test_parses_json_wrapped_line():
    """Последнее поле в выгрузке склеено с обёрткой — число обязано дочитаться."""
    usage = probe.parse_usage_line(WRAPPED)
    assert usage is not None and usage.operation == "chat"
    assert usage.total_tokens == 572, "хвост JSON-обёртки съел total_tokens"

    tts = probe.parse_usage_line(TTS_WRAPPED)
    assert tts is not None and tts.kind == "tts" and tts.operation == "synthesis"
    assert (tts.chars, tts.duration_ms, tts.audio_bytes) == (884, 59040, 176032)


def test_counts_billed_requests_not_log_lines():
    """С 02.09.2026 длинный текст режется на куски: одна строка = несколько платных вызовов."""
    line = ("tts_request api=v3 voice=alena role=good fmt=mp3 chars=610 "
            "duration_ms=41000 bytes=120000 requests=3")
    usage = probe.parse_usage_line(line)
    assert usage is not None and usage.requests == 3
    old = probe.parse_usage_line("tts_request api=v3 voice=alena role=good fmt=mp3 "
                                 "chars=100 duration_ms=7000 bytes=1000")
    assert old is not None and old.requests is None, "у старых строк поля нет"
    totals = probe.summarize([usage, old], [])["totals"]
    assert totals["tts_requests"] == 4, "строка без поля считается за один запрос"


def test_foreign_lines_are_ignored():
    assert probe.parse_usage_line("INFO uvicorn Application startup complete.") is None
    assert probe.parse_usage_line("") is None


def test_missing_numbers_are_none_not_zero():
    """`input_tokens=None` в логе — «не пришло», и в медиану такой вызов не входит."""
    usage = probe.parse_usage_line("llm_usage operation=story model=- model_version=- "
                                   "input_tokens=None output_tokens=None total_tokens=None")
    assert usage is not None
    assert usage.input_tokens is None and usage.total_tokens is None
    stats = probe.summarize([usage, _call("story", input_tokens=100)], [])
    assert stats["by_operation"]["story"]["input_tokens"]["median"] == 100


# ── 2. Формат не разъехался с приложением ───────────────────────────────────
def test_reads_the_line_the_app_actually_writes():
    """Строку пишет настоящий llm._log_usage — иначе тест проверял бы сам себя."""
    with collector_attached() as handler:
        previous = settings.llm_log_usage
        settings.llm_log_usage = True
        try:
            llm._log_usage(
                "chat",
                "gpt://b1g/yandexgpt/latest",
                {"usage": {"inputTextTokens": "412", "completionTokens": "180", "totalTokens": "592"},
                 "modelVersion": "23.10.2024"},
            )
        finally:
            settings.llm_log_usage = previous
        collected = handler.drain()
    assert len(collected) == 1, "строка расхода приложения перестала разбираться"
    usage = collected[0]
    assert (usage.operation, usage.input_tokens, usage.output_tokens, usage.total_tokens) == \
        ("chat", 412, 180, 592)


def test_tts_line_keeps_the_fields_we_read():
    """У tts_request нет функции-обёртки, поэтому сторожим поля по исходнику."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "app", "services", "tts.py")
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    line = next(l for l in source.splitlines() if probe.TTS_MARKER in l and "%s" in l)
    for field in ("chars=", "duration_ms=", "bytes="):
        assert field in line, f"из строки синтеза пропало поле {field}"


# ── 3. Медианы ───────────────────────────────────────────────────────────────
def test_medians_by_operation():
    calls = [
        _call("story", input_tokens=600, output_tokens=200, total_tokens=800),
        _call("story", input_tokens=700, output_tokens=300, total_tokens=1000),
        _call("story", input_tokens=800, output_tokens=250, total_tokens=1050),
        probe.Usage(kind="tts", operation="synthesis", chars=900),
        probe.Usage(kind="tts", operation="synthesis", chars=500),
    ]
    summary = probe.summarize(calls, [])
    story = summary["by_operation"]["story"]
    assert story["calls"] == 3
    assert story["input_tokens"]["median"] == 700
    assert (story["output_tokens"]["min"], story["output_tokens"]["max"]) == (200, 300)
    assert story["total_tokens"]["sum"] == 2850
    assert summary["by_operation"]["synthesis"]["chars"]["median"] == 700
    assert summary["totals"]["tts_requests"] == 2


def test_per_visitor_is_sum_then_median():
    """Сначала суммируем по экспонату, потом берём медиану — не наоборот."""
    calls = [
        _call("story", input_tokens=600, output_tokens=200, total_tokens=800, exhibit_id=1),
        _call("chat", input_tokens=400, output_tokens=100, total_tokens=500, exhibit_id=1),
        _call("story", input_tokens=500, output_tokens=150, total_tokens=650, exhibit_id=2),
        _call("chat", input_tokens=300, output_tokens=50, total_tokens=350, exhibit_id=2),
        probe.Usage(kind="tts", operation="synthesis", chars=900, exhibit_id=1),
        probe.Usage(kind="tts", operation="synthesis", chars=700, exhibit_id=2),
    ]
    per = probe.summarize(calls, [])["per_exhibit"]
    assert per["exhibits"] == 2
    assert per["input_tokens"] == 900          # медиана из 1000 и 800
    assert per["total_tokens"] == 1150         # медиана из 1300 и 1000
    assert per["tts_chars"] == 800


def test_per_visitor_is_skipped_for_logs():
    """В логах прода привязки к экспонату нет — блок «на посетителя» не выдумываем."""
    assert probe.summarize([_call("chat", input_tokens=10)], [])["per_exhibit"] == {}


# ── 4. Привязка вызова к шагу сценария ──────────────────────────────────────
class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeClient:
    """Клиент, который на каждый запрос пишет строку расхода — как настоящие ручки."""

    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.urls = []

    async def post(self, url, json=None):  # noqa: A002 — сигнатура httpx
        self.urls.append(url)
        logging.getLogger("app.services.llm").info(
            "llm_usage operation=%s model=gpt://b1g/yandexgpt/latest model_version=x "
            "input_tokens=%s output_tokens=%s total_tokens=%s",
            "story" if "story" in url else "chat", 400, 120, 520,
        )
        return self._responses.pop(0)


def test_step_tags_the_call_with_exhibit_and_step():
    calls, steps = [], []
    with collector_attached() as handler:
        client = FakeClient([FakeResponse(200, {"text": "рассказ", "suggested_questions": ["Кто автор?"]})])
        payload = asyncio.run(probe._post(client, "/guide/story", {}, 144, "story", handler, calls, steps))
    assert payload["text"] == "рассказ"
    assert len(calls) == 1 and calls[0].exhibit_id == 144 and calls[0].step == "story"
    assert steps[0].status == 200 and steps[0].chars == len("рассказ")


def test_failed_step_still_counts_the_paid_call():
    """502 после ответа модели оплачен — вызов обязан остаться в сводке."""
    calls, steps = [], []
    with collector_attached() as handler:
        client = FakeClient([FakeResponse(502, None, "Сервис генерации текста временно недоступен.")])
        payload = asyncio.run(probe._post(client, "/guide/chat", {}, 7, "chat1", handler, calls, steps))
    assert payload is None
    assert len(calls) == 1 and calls[0].step == "chat1"
    assert steps[0].status == 502 and "недоступен" in steps[0].detail
    assert probe.summarize(calls, steps)["by_step"]["chat1"]["failed"] == 1


def test_previous_step_lines_do_not_leak_into_the_next():
    """Строки, накопленные до шага, к нему не приписываются."""
    calls, steps = [], []
    with collector_attached() as handler:
        logging.getLogger("app.services.tts").info(
            "tts_request api=v3 voice=alena role=good fmt=mp3 chars=100 duration_ms=7000 bytes=1000"
        )
        client = FakeClient([FakeResponse(200, {"answer": "ответ", "session_id": "s-1"})])
        asyncio.run(probe._post(client, "/guide/chat", {}, 7, "chat1", handler, calls, steps))
    assert [c.operation for c in calls] == ["chat"], "в шаг попала чужая строка расхода"
    assert steps[0].chars == len("ответ")


# ── 5. Режим remote: логи облака ─────────────────────────────────────────────
# Строка, как её реально пишет Cloud Functions (снята с прода 02.09.2026):
# перед нашим текстом стоит уровень, метка времени и RequestID через табы.
PROD_LINE = (
    "[INFO]\t2026-09-02T04:18:50.446Z\td95408ec-f260-4cf6-93ca-7b5166f46637\t"
    "llm_usage operation=story model=gpt://b1glrl280tkmpcnt3p1l/yandexgpt/latest "
    "model_version=09.02.2025 input_tokens=374 output_tokens=116 total_tokens=490"
)


def test_parses_the_line_as_cloud_functions_writes_it():
    usage = probe.parse_usage_line(PROD_LINE)
    assert usage is not None and usage.operation == "story"
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (374, 116, 490)


def test_entry_moment_takes_nanoseconds():
    """yc отдаёт метку с наносекундами — datetime столько не берёт, и это не повод терять строку."""
    moment = probe._entry_moment({"timestamp": "2026-09-02T04:18:50.447455617Z"})
    assert moment is not None
    assert abs(moment - 1788322730.447455) < 0.001
    assert probe._entry_moment({"timestamp": "мусор"}) is None


def test_attribute_by_time_assigns_step_and_keeps_orphans_visible():
    """Прогон последовательный, поэтому окно шага однозначно определяет владельца строки."""
    steps = [
        probe.Step(144, "story", 200, 900.0, started_at=1000.0, finished_at=1005.0),
        probe.Step(144, "chat1", 200, 700.0, started_at=1010.0, finished_at=1014.0),
    ]
    entries = [
        (1004.5, probe.Usage(kind="llm", operation="story", input_tokens=374)),
        (1013.0, probe.Usage(kind="llm", operation="chat", input_tokens=400)),
        (9999.0, probe.Usage(kind="llm", operation="chat", input_tokens=1)),   # чужой трафик
    ]
    calls, orphans = probe.attribute_by_time(entries, steps, slack=1.0)
    assert [(c.exhibit_id, c.step) for c in calls[:2]] == [(144, "story"), (144, "chat1")]
    assert orphans == 1 and calls[2].exhibit_id is None, "чужую строку нельзя приписать экспонату"
    assert len(calls) == 3, "непривязанные строки остаются в общих медианах"


def test_read_cloud_logs_says_what_went_wrong():
    """Нет yc — внятная строка, а не трассировка: режим remote без CLI бессмыслен."""
    found, problem = probe.read_cloud_logs("default", 0.0, 1.0, yc_bin="yc-которого-нет")
    assert found == [] and "yc-которого-нет" in problem


# ── 6. Контракт ручек ────────────────────────────────────────────────────────
def _args(**over):
    defaults = dict(style="engaging", language="ru", max_questions=4, voice="alena", audio_format="mp3")
    defaults.update(over)
    return argparse.Namespace(**defaults)


def test_request_bodies_validate_against_the_app_schemas():
    """Тела запросов проверяются настоящими схемами: уедет контракт — упадёт тест, а не прогон."""
    args = _args()
    story = sch.StoryRequest(**probe.story_body(144, args))
    assert story.exhibit_id == 144 and story.include_audio is False, "рассказ не должен тянуть озвучку внутри себя"

    first = sch.ChatRequest(**probe.chat_body(144, "Кто автор?", None, args))
    assert first.context is not None and first.context.exhibit_id == 144
    assert "context" in first.model_fields_set, "первая реплика обязана задать контекст экспоната"

    uuid_like = "0f9a4f1e-6f7c-4f6a-9c1e-2b3d4e5f6a7b"
    second = sch.ChatRequest(**probe.chat_body(144, "А почему?", uuid_like, args))
    assert str(second.session_id) == uuid_like
    # Явный `context: null` на второй реплике означал бы СБРОС контекста
    # (баг-репорт 28.07.2026, п.3): диалог ушёл бы в общий чат, а замер мерил бы
    # не то, что просили.
    assert "context" not in second.model_fields_set

    speech = sch.SpeechRequest(**probe.speech_body("Текст рассказа", args))
    assert speech.text == "Текст рассказа" and speech.format.value == "mp3"


def test_defaults_match_the_agreed_run():
    """Умолчания — тот прогон, о котором договаривались: 10–15 карточек, пара вопросов, озвучка."""
    args = probe.build_parser().parse_args([])
    assert 10 <= args.count <= 15, "прогон по умолчанию должен быть на 10–15 экспонатах"
    assert args.turns == 2 and args.source == "live"
    assert args.apply is False, "платный прогон не должен запускаться без --apply"


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
