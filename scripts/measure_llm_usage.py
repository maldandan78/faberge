#!/usr/bin/env python3
"""Замер расхода LLM и SpeechKit на прогоне 10–15 экспонатов (запрос 02.09.2026).

Что меряется. Сценарий одного посетителя у витрины, целиком:

    рассказ (``POST /guide/story``)
      + N уточняющих вопросов в чате (``POST /guide/chat``, по умолчанию 2)
      + озвучка рассказа (``POST /speech``)

и так по каждому эксподанту выборки. На выходе — медианы input/output токенов по
каждой операции LLM (``story`` / ``chat`` / ``questions`` / ``tts_spoken``),
медиана символов синтеза, суммы за прогон и медиана «на одного посетителя»
(рассказ + вопросы + озвучка одного экспоната).

Откуда берутся токены. Из тех же строк расхода, что пишутся на проде
(``app/services/llm._log_usage`` и ``app/services/tts._synthesize_yandex``,
задача 19.08.2026, п.5):

    llm_usage operation=chat model=gpt://…/yandexgpt/latest model_version=… input_tokens=412 output_tokens=180 total_tokens=592
    tts_request api=v3 voice=alena role=good fmt=mp3 chars=284 duration_ms=19040 bytes=76032

В API эти числа не возвращаются, поэтому у скрипта два источника — и оба
разбираются одним и тем же парсером:

``--source live`` (по умолчанию)
    Прогон выполняется В ЭТОМ ЖЕ ПРОЦЕССЕ: приложение поднимается через ASGI
    (``httpx.ASGITransport``), запросы идут в настоящие ручки ``/guide/story``,
    ``/guide/chat``, ``/speech``, а строки расхода перехватываются обработчиком
    логов. Поэтому каждый вызов привязан к экспонату и шагу сценария — медиану
    «на посетителя» иначе не собрать. Нужны DATABASE_URL и ключи Yandex Cloud.

``--source remote``
    Прогон по HTTP против развёрнутого стенда/прода (``--base-url``): ни БД, ни
    ключей на машине не нужно — считает та же функция, что обслуживает
    посетителей. Строки расхода забираются после прогона из Cloud Logging
    (``yc logging read``, ``--log-group``) и привязываются к шагу ПО ВРЕМЕНИ:
    прогон строго последовательный, в полёте всегда один запрос, поэтому окно
    шага однозначно определяет, чей это расход. Строки, не попавшие ни в одно
    окно (чужой трафик на стенде), считаются отдельно и в разбивку по экспонатам
    не идут — в отчёте про это сказано прямо.

``--source log``
    Те же строки, но из готовой выгрузки логов (файл или stdin, в том числе
    JSON-обёртка Cloud Logging — строка ищется подстрокой). Токены настоящие, с
    живого трафика; привязки к экспонату и шагу в логах нет, поэтому блок «на
    одного посетителя» в этом режиме не печатается.

Деньги. ``--source live`` — платный прогон, поэтому по умолчанию это СУХОЙ
ПРОГОН: печатается выборка и план вызовов, ни один запрос в облако не уходит.
Реальный замер включается ключом ``--apply`` (как в scripts/warm_guide_questions.py).

Запуск:

    DATABASE_URL=... YANDEX_API_KEY=... YANDEX_FOLDER_ID=... \\
        python scripts/measure_llm_usage.py                      # сухой прогон, план
    ... --apply                                                  # замер: 12 экспонатов × (рассказ + 2 вопроса + озвучка)
    ... --apply --count 15 --turns 2 --csv usage.csv --json usage.json
    ... --apply --ids 144,483,512                                # точечно, на своей выборке
    yc logging read --group-name default --since 24h | \\
        python scripts/measure_llm_usage.py --source log -       # медианы по живому трафику

Что учесть при чтении цифр:

  • ``operation=questions`` в прогоне может не появиться вовсе — вопросы-подсказки
    с 26.08.2026 берутся из кэша в БД (``exhibit_questions``). Ноль вызовов здесь
    означает «кэш прогрет», а не «не померили»; чтобы увидеть цену генерации,
    прогоните ``scripts/warm_guide_questions.py --force --apply --ids …``;
  • ``operation=tts_spoken`` — это lite-модель («Пётр I» → «Пётр Первый») перед
    синтезом. Вызова не будет, если в тексте нет чисел или он уже в процессном
    кэше ``tts._SPOKEN_CACHE`` (у скрипта процесс свежий, кэш пустой);
  • синтез оплачивается каждый прогон: ``tts._synthesize_yandex`` кладёт файл в
    Object Storage, но перед запросом в кэш не смотрит;
  • диалог оставляет в БД сессию и реплики — ровно как заход посетителя с
    телефона (так же ведёт себя scripts/smoke_bugreport_20260831.py). Каталог
    скрипт не меняет;
  • режим remote с адресом прода — это настоящие деньги и настоящие следы
    посетителя в базе. `--retries` там не украшение: шлюз отдаёт 502 на холодном
    инстансе, и без повторов выборка рассыпается.

Стоимость в рублях намеренно не считается: прайс Yandex Cloud сверяется на дату
прогона, а не по памяти (см. docs/task-2026-08-19-llm-cost.md). Сумм по input /
output / запросам синтеза для умножения на прайс скрипт печатает достаточно.

Коды возврата: 0 — прогон удался, 1 — часть экспонатов упала (или строк расхода
не нашлось), 2 — ошибка конфигурации (нет выборки, выключен LLM_LOG_USAGE, не
читается файл логов).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Маркеры строк расхода. Значения намеренно совпадают с тем, что пишет
# приложение: меняется формат в app/services — правится здесь, тест
# tests/test_llm_usage_probe.py ловит расхождение.
LLM_MARKER = "llm_usage"
TTS_MARKER = "tts_request"

# Запасные вопросы для чата: берём подсказки из ответа /guide/story (посетитель
# тапает по ним), а если их нет — эти. Формулировки нарочно общие: замер меряет
# длину контекста и ответа, а не эрудицию модели по конкретной карточке.
FALLBACK_QUESTIONS = [
    "Кто и когда создал этот предмет?",
    "Почему он считается ценным?",
    "Для кого он был сделан?",
]


# ── Модель данных ────────────────────────────────────────────────────────────
@dataclass
class Usage:
    """Один платный вызов: строка llm_usage или tts_request."""

    kind: str                       # "llm" | "tts"
    operation: str                  # story | chat | questions | tts_spoken | complete | synthesis
    model: str = "-"
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    chars: Optional[int] = None
    duration_ms: Optional[int] = None
    audio_bytes: Optional[int] = None
    # Сколько ПЛАТНЫХ вызовов SpeechKit стоит за строкой: с 02.09.2026 длинный
    # текст режется на куски (tts.split_for_v3), и строка лога больше не равна
    # одному запросу. У старых строк поля нет — считаем такую строку за один.
    requests: Optional[int] = None
    # Проставляются только в режиме live: в логах прода привязки нет.
    exhibit_id: Optional[int] = None
    step: str = ""                  # story | chat1 | chat2 | speech


@dataclass
class Step:
    """Один HTTP-вызов сценария — для медианы задержки и разбора провалов."""

    exhibit_id: int
    step: str
    status: int
    latency_ms: float
    detail: str = ""
    chars: Optional[int] = None     # длина текста рассказа / символы синтеза
    # Границы шага в UTC-секундах. В режиме remote расход считает не наш процесс,
    # а функция в облаке: строку из Cloud Logging приписываем шагу по времени.
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class Sample:
    exhibit_id: int
    name: str
    description_chars: int
    calls: List[Usage] = field(default_factory=list)


# ── Разбор строк расхода ─────────────────────────────────────────────────────
def _as_int(value: Optional[str]) -> Optional[int]:
    """`-`, `None` и мусор из обёртки лога — это «нет числа», а не ноль."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# Значение в строке расхода — «слово» без пробелов, кавычек и запятых
# (`gpt://…/yandexgpt/latest`, `592`, `alena`). Всё, что идёт после первой
# кавычки/запятой/скобки, — это уже обёртка выгрузки: Cloud Logging отдаёт нашу
# строку внутри JSON, и последнее поле приезжает как `total_tokens=592","stream":…`.
_VALUE_RE = re.compile(r'[^"\\,}\s]*')


def _fields(tail: str) -> Dict[str, str]:
    """Разобрать хвост строки в key=value. Первый токен без «=» — конец строки."""
    out: Dict[str, str] = {}
    for token in tail.split():
        if "=" not in token:
            break
        key, value = token.split("=", 1)
        out[key] = _VALUE_RE.match(value.lstrip('"\\')).group(0)
    return out


def parse_usage_line(line: str) -> Optional[Usage]:
    """Вернуть Usage, если в строке есть llm_usage/tts_request, иначе None."""
    for marker, kind in ((LLM_MARKER, "llm"), (TTS_MARKER, "tts")):
        index = line.find(marker + " ")
        if index < 0:
            continue
        f = _fields(line[index + len(marker):])
        if kind == "llm":
            return Usage(
                kind="llm",
                operation=f.get("operation", "-"),
                model=f.get("model", "-"),
                input_tokens=_as_int(f.get("input_tokens")),
                output_tokens=_as_int(f.get("output_tokens")),
                total_tokens=_as_int(f.get("total_tokens")),
            )
        return Usage(
            kind="tts",
            # Своё имя операции: в строке tts_request поля operation нет, а в
            # сводке синтез должен стоять рядом с операциями LLM.
            operation="synthesis",
            model=f.get("api", "-"),
            chars=_as_int(f.get("chars")),
            duration_ms=_as_int(f.get("duration_ms")),
            audio_bytes=_as_int(f.get("bytes")),
            requests=_as_int(f.get("requests")),
        )
    return None


class UsageCollector(logging.Handler):
    """Перехват строк расхода из логов приложения в этом же процессе."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.collected: List[Usage] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — сломанный формат чужой строки не наш случай
            return
        usage = parse_usage_line(message)
        if usage is not None:
            self.collected.append(usage)

    def drain(self) -> List[Usage]:
        out, self.collected = self.collected, []
        return out


# ── Сводка ───────────────────────────────────────────────────────────────────
def _median(values: Sequence[Optional[int]]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return statistics.median(clean) if clean else None


def _stats(values: Sequence[Optional[int]]) -> Dict[str, Optional[float]]:
    clean = [v for v in values if v is not None]
    if not clean:
        return {"median": None, "min": None, "max": None, "sum": None}
    return {
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
        "sum": sum(clean),
    }


def summarize(calls: Sequence[Usage], steps: Sequence[Step],
              estimates: Sequence[int] = ()) -> Dict:
    """Медианы по операциям, по шагам сценария и «на одного посетителя»."""
    by_operation: Dict[str, Dict] = {}
    for operation in sorted({c.operation for c in calls}):
        rows = [c for c in calls if c.operation == operation]
        by_operation[operation] = {
            "kind": rows[0].kind,
            "calls": len(rows),
            "input_tokens": _stats([r.input_tokens for r in rows]),
            "output_tokens": _stats([r.output_tokens for r in rows]),
            "total_tokens": _stats([r.total_tokens for r in rows]),
            "chars": _stats([r.chars for r in rows]),
            "duration_ms": _stats([r.duration_ms for r in rows]),
        }

    # «На одного посетителя»: суммы по экспонату, затем медиана по экспонатам.
    # Считается только там, где привязка есть (режим live).
    per_exhibit: Dict[str, Optional[float]] = {}
    tagged = [c for c in calls if c.exhibit_id is not None]
    if tagged:
        totals: Dict[int, Dict[str, int]] = {}
        for call in tagged:
            bucket = totals.setdefault(
                call.exhibit_id, {"input": 0, "output": 0, "total": 0, "tts_chars": 0, "tts_requests": 0}
            )
            bucket["input"] += call.input_tokens or 0
            bucket["output"] += call.output_tokens or 0
            bucket["total"] += call.total_tokens or 0
            if call.kind == "tts":
                bucket["tts_chars"] += call.chars or 0
                bucket["tts_requests"] += call.requests or 1
        per_exhibit = {
            "exhibits": len(totals),
            "input_tokens": _median([b["input"] for b in totals.values()]),
            "output_tokens": _median([b["output"] for b in totals.values()]),
            "total_tokens": _median([b["total"] for b in totals.values()]),
            "tts_chars": _median([b["tts_chars"] for b in totals.values()]),
            "tts_requests": _median([b["tts_requests"] for b in totals.values()]),
        }

    by_step: Dict[str, Dict] = {}
    for name in sorted({s.step for s in steps}):
        rows = [s for s in steps if s.step == name]
        ok = [s for s in rows if 200 <= s.status < 300]
        by_step[name] = {
            "requests": len(rows),
            "failed": len(rows) - len(ok),
            "latency_ms_median": _median([int(s.latency_ms) for s in ok]),
            "chars_median": _median([s.chars for s in ok]),
        }

    return {
        "calls": len(calls),
        # Оценка объёма синтеза для шагов, где SpeechKit не ответил (см.
        # _estimated_tts_chars). Замером не притворяется — печатается отдельно.
        "tts_chars_estimate": _stats(list(estimates)),
        "by_operation": by_operation,
        "by_step": by_step,
        "per_exhibit": per_exhibit,
        "totals": {
            "input_tokens": sum(c.input_tokens or 0 for c in calls),
            "output_tokens": sum(c.output_tokens or 0 for c in calls),
            "total_tokens": sum(c.total_tokens or 0 for c in calls),
            "llm_calls": sum(1 for c in calls if c.kind == "llm"),
            "tts_requests": sum((c.requests or 1) for c in calls if c.kind == "tts"),
            "tts_chars": sum(c.chars or 0 for c in calls if c.kind == "tts"),
        },
    }


def _num(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def print_report(summary: Dict, title: str) -> None:
    print("")
    print(title)
    print("")
    llm_ops = {k: v for k, v in summary["by_operation"].items() if v["kind"] == "llm"}
    if llm_ops:
        print("LLM (llm_usage), токены")
        print(f"  {'операция':<12} {'вызовов':>7} {'input: мед':>11} {'мин':>7} {'макс':>7} "
              f"{'output: мед':>12} {'мин':>7} {'макс':>7} {'сумма total':>12}")
        for operation, row in llm_ops.items():
            i, o, t = row["input_tokens"], row["output_tokens"], row["total_tokens"]
            print(f"  {operation:<12} {row['calls']:>7} {_num(i['median']):>11} {_num(i['min']):>7} "
                  f"{_num(i['max']):>7} {_num(o['median']):>12} {_num(o['min']):>7} {_num(o['max']):>7} "
                  f"{_num(t['sum']):>12}")
        print("")

    tts = summary["by_operation"].get("synthesis")
    if tts:
        chars, duration = tts["chars"], tts["duration_ms"]
        print("SpeechKit (tts_request)")
        billed = summary["totals"]["tts_requests"]
        print(f"  строк лога: {tts['calls']}   платных запросов: {billed}   "
              f"символов: мед {_num(chars['median'])}, мин {_num(chars['min'])}, макс {_num(chars['max'])}, "
              f"сумма {_num(chars['sum'])}")
        print(f"  длительность аудио, мс: мед {_num(duration['median'])}, макс {_num(duration['max'])}")
        print("")

    estimate = summary.get("tts_chars_estimate") or {}
    if estimate.get("median") is not None:
        print("Озвучка (ОЦЕНКА, синтез не ответил): символов после нормализации чисел — "
              f"мед {_num(estimate['median'])}, мин {_num(estimate['min'])}, макс {_num(estimate['max'])}, "
              f"сумма {_num(estimate['sum'])}")
        print("")

    if summary["per_exhibit"]:
        p = summary["per_exhibit"]
        print(f"На одного посетителя (экспонат целиком, медиана по {p['exhibits']} экспонатам)")
        print(f"  input: {_num(p['input_tokens'])}   output: {_num(p['output_tokens'])}   "
              f"total: {_num(p['total_tokens'])}   символов синтеза: {_num(p['tts_chars'])}")
        print("")

    if summary["by_step"]:
        print("Шаги сценария")
        print(f"  {'шаг':<10} {'запросов':>9} {'провалов':>9} {'задержка мед, мс':>18} {'знаков мед':>12}")
        for name, row in summary["by_step"].items():
            print(f"  {name:<10} {row['requests']:>9} {row['failed']:>9} "
                  f"{_num(row['latency_ms_median']):>18} {_num(row['chars_median']):>12}")
        print("")

    totals = summary["totals"]
    print("Итого за прогон")
    print(f"  вызовов LLM: {totals['llm_calls']}   input: {totals['input_tokens']}   "
          f"output: {totals['output_tokens']}   total: {totals['total_tokens']}")
    print(f"  запросов синтеза: {totals['tts_requests']}   символов: {totals['tts_chars']}")
    print("  Стоимость: умножьте суммы на действующий прайс Yandex Cloud "
          "(v3 SpeechKit тарифицируется по запросам, не по символам).")


# ── Источник: логи ───────────────────────────────────────────────────────────
def run_from_log(path: str) -> Tuple[List[Usage], List[Step]]:
    stream = sys.stdin if path == "-" else open(path, "r", encoding="utf-8", errors="replace")
    try:
        calls = [u for u in (parse_usage_line(line) for line in stream) if u is not None]
    finally:
        if stream is not sys.stdin:
            stream.close()
    return calls, []


# ── Источник: прогон по HTTP + логи облака ──────────────────────────────────
def attribute_by_time(entries: Sequence[Tuple[float, Usage]], steps: Sequence[Step],
                      slack: float = 5.0) -> Tuple[List[Usage], int]:
    """Приписать строки расхода шагам сценария по времени.

    В режиме remote вызовы делает функция в облаке, и привязки «строка → экспонат»
    в логе нет. Зато прогон СТРОГО последовательный: в каждый момент в полёте один
    запрос, поэтому окно шага (start … finish + запас на доставку лога) однозначно
    определяет, чей это расход. Запас нужен из-за расхождения часов и лага
    ingestion; строки, не попавшие ни в одно окно, не выбрасываются молча — их
    число возвращается вторым значением и печатается в отчёте.
    """
    windows = [s for s in steps if s.started_at is not None and s.finished_at is not None]
    attributed: List[Usage] = []
    orphans = 0
    for moment, usage in entries:
        match = None
        for step in windows:
            if step.started_at - slack <= moment <= step.finished_at + slack:
                match = step
                break
        if match is None:
            orphans += 1
            attributed.append(usage)
            continue
        usage.exhibit_id = match.exhibit_id
        usage.step = match.step
        attributed.append(usage)
    return attributed, orphans


def _entry_text(entry: Dict) -> str:
    """Текст записи Cloud Logging: сообщение плюс структурная часть, если она есть."""
    text = entry.get("message") or ""
    payload = entry.get("json_payload")
    if payload:
        text = f"{text} {json.dumps(payload, ensure_ascii=False)}"
    return text


# Метка времени Cloud Logging: RFC-3339, дробная часть бывает наносекундной
# (datetime столько не берёт), зона — Z или ±HH:MM.
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$")


def _entry_moment(entry: Dict) -> Optional[float]:
    """UTC-секунды записи лога или None, если метка нечитаемая."""
    match = _TS_RE.match((entry.get("timestamp") or "").strip())
    if not match:
        return None
    head, fraction, zone = match.groups()
    micro = (fraction or "0")[:6].ljust(6, "0")
    if zone in (None, "Z", "z"):
        zone = "+00:00"
    elif ":" not in zone:
        zone = f"{zone[:3]}:{zone[3:]}"
    try:
        return datetime.fromisoformat(f"{head}.{micro}{zone}").timestamp()
    except ValueError:
        return None


def read_cloud_logs(group: str, since: float, until: float, yc_bin: str = "yc",
                    limit: int = 5000) -> Tuple[List[Tuple[float, Usage]], str]:
    """Вытащить строки расхода из Cloud Logging за окно прогона (yc logging read)."""
    import subprocess

    def _iso(moment: float) -> str:
        return datetime.fromtimestamp(moment, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    command = [yc_bin, "logging", "read", group, "--since", _iso(since), "--until", _iso(until),
               "--limit", str(limit), "--format", "json"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        return [], f"не найден {yc_bin} — поставьте Yandex Cloud CLI или укажите --yc"
    except subprocess.TimeoutExpired:
        return [], "yc logging read не ответил за 180 с (бывает; повторите с тем же --window)"
    if completed.returncode != 0:
        return [], f"yc logging read вернул {completed.returncode}: {completed.stderr.strip()[:200]}"
    try:
        entries = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return [], "не разобрался ответ yc logging read (ожидался JSON)"

    found: List[Tuple[float, Usage]] = []
    for entry in entries:
        usage = parse_usage_line(_entry_text(entry))
        if usage is None:
            continue
        moment = _entry_moment(entry)
        if moment is None:
            continue
        found.append((moment, usage))
    found.sort(key=lambda pair: pair[0])
    return found, ""


# ── Источник: прогон сценария ────────────────────────────────────────────────
async def _pick_exhibits(session, count: int, ids: Optional[List[int]], min_chars: int) -> List[Sample]:
    """Выборка экспонатов: явные --ids либо равномерно по каталогу.

    Равномерно, а не «первые N»: подряд идущие id — это одна витрина, у них
    похожие описания, и медиана по ним меряла бы одну карточку, а не каталог.
    Служебные залы исключаются — посетитель до них не доходит.
    """
    from sqlalchemy import func, or_, select

    from app import models as m

    service_showcases = (
        select(m.Showcase.id).join(m.Hall, m.Showcase.hall_id == m.Hall.id).where(m.Hall.is_service.is_(True))
    )
    stmt = select(m.Exhibit.id, m.Exhibit.name, func.coalesce(func.length(m.Exhibit.short_description), 0))
    if ids:
        stmt = stmt.where(m.Exhibit.id.in_(ids))
    else:
        stmt = stmt.where(
            func.coalesce(func.length(m.Exhibit.short_description), 0) >= min_chars,
            or_(m.Exhibit.showcase_id.is_(None), m.Exhibit.showcase_id.not_in(service_showcases)),
        )
    rows = list((await session.execute(stmt.order_by(m.Exhibit.id))).all())
    if ids or len(rows) <= count:
        chosen = rows
    else:
        stride = len(rows) / count
        chosen = [rows[int(i * stride)] for i in range(count)]
    return [Sample(exhibit_id=r[0], name=r[1], description_chars=r[2]) for r in chosen]


# ── Тела запросов ────────────────────────────────────────────────────────────
# Вынесены из сценария, чтобы тест мог прогнать их через настоящие схемы
# (app/schemas.py): «замер сломался, потому что контракт ручки уехал» —
# худший вид провала, он выглядит как подорожавшая модель.
def story_body(exhibit_id: int, args: argparse.Namespace) -> Dict:
    return {
        "exhibit_id": exhibit_id,
        "style": args.style,
        "language": args.language,
        "include_audio": False,   # озвучка меряется отдельным шагом /speech
        "max_questions": args.max_questions,
    }


def chat_body(exhibit_id: int, question: str, session_id: Optional[str], args: argparse.Namespace) -> Dict:
    body: Dict = {"message": question, "language": args.language, "max_questions": args.max_questions}
    if session_id is None:
        # Первая реплика заводит сессию и задаёт контекст экспоната; дальше
        # контекст не шлём — его подставляет сама сессия (и это путь фронта).
        body["context"] = {"exhibit_id": exhibit_id}
    else:
        body["session_id"] = session_id
    return body


def speech_body(text: str, args: argparse.Namespace) -> Dict:
    return {"text": text, "voice": args.voice, "format": args.audio_format}


async def _post(client, url: str, body: Dict, exhibit_id: int, step: str,
                collector: Optional[UsageCollector], calls: List[Usage], steps: List[Step],
                retries: int = 0, retry_pause: float = 2.0) -> Optional[Dict]:
    """Один шаг сценария: запрос, окно времени и строки расхода, порождённые им.

    ``collector`` есть только в режиме live (приложение работает в этом процессе).
    В режиме remote расход пишет функция в облаке — строки приезжают потом, из
    Cloud Logging, и привязываются к шагу по окну ``started_at``…``finished_at``.

    Повторы нужны прод-шлюзу: он отдаёт 502 на холодном инстансе. КАЖДАЯ попытка
    записывается отдельным шагом — неудачная тоже могла быть оплачена, и её окно
    обязано остаться в привязке.
    """
    for attempt in range(retries + 1):
        if collector is not None:
            collector.drain()  # чужие строки (прошлый шаг) в этот шаг не считаем
        started = time.time()
        started_perf = time.perf_counter()
        status, detail, payload = 0, "", None
        try:
            response = await client.post(url, json=body)
            status = response.status_code
            if status == 200:
                payload = response.json()
            else:
                detail = response.text[:200]
        except Exception as exc:  # noqa: BLE001 — сеть/таймаут не должны ронять прогон
            detail = str(exc)[:200]
        finished = time.time()
        latency = (time.perf_counter() - started_perf) * 1000

        # Строки расхода забираем и у провалившегося шага: 502 после ответа
        # модели всё равно оплачен, и в сводке он должен быть виден.
        if collector is not None:
            for usage in collector.drain():
                usage.exhibit_id = exhibit_id
                usage.step = step
                calls.append(usage)
        # Знаки шага: у /speech это оплаченные символы синтеза, у рассказа и
        # ответа гида — длина текста (видно, попадаем ли в GUIDE_STORY_MAX_CHARS).
        chars = None
        if payload:
            text = payload.get("text") or payload.get("answer")
            chars = payload.get("characters") or (len(text) if text else None)
        steps.append(Step(exhibit_id, step, status, latency, detail, chars, started, finished))
        if payload is not None:
            return payload
        if attempt < retries:
            print(f"    повтор {attempt + 1}/{retries}: {status or 'нет ответа'} {detail[:60]}", flush=True)
            await asyncio.sleep(retry_pause)
    return None


def _estimated_tts_chars(text: str) -> Optional[int]:
    """Сколько символов ушло бы в синтез: текст после нормализации чисел.

    Оценка, а не замер: на проде числа переписывает lite-модель, здесь — её
    детерминированный дублёр (`text_normalize.normalize_for_tts`, тот же путь,
    что работает без LLM). Нужна ровно тогда, когда синтез на стенде лежит:
    без неё «медиана символов озвучки» была бы пустой клеткой.
    """
    if not text:
        return None
    try:
        from app.services.text_normalize import normalize_for_tts
    except Exception:  # noqa: BLE001 — скрипт умеет работать в отрыве от репозитория
        return len(text)
    return len(normalize_for_tts(text))


async def _run_scenario(client, samples: List[Sample], args: argparse.Namespace,
                        collector: Optional[UsageCollector], calls: List[Usage],
                        steps: List[Step], estimates: Optional[List[int]] = None) -> int:
    """Сценарий посетителя по всей выборке. Возвращает число упавших шагов."""
    failed = 0
    estimates = estimates if estimates is not None else []
    retries = getattr(args, "retries", 0)
    for index, sample in enumerate(samples, start=1):
        print(f"[{index}/{len(samples)}] id={sample.exhibit_id} {sample.name[:50]}", flush=True)
        story = await _post(client, "/guide/story", story_body(sample.exhibit_id, args),
                            sample.exhibit_id, "story", collector, calls, steps, retries)
        if story is None:
            failed += 1
            continue

        # Вопросы берём из подсказок ответа — это и есть путь посетителя
        # («тапнул по подсказке»), и длина реплики тогда настоящая.
        suggestions = list(story.get("suggested_questions") or [])
        session_id: Optional[str] = None
        for turn in range(1, args.turns + 1):
            question = suggestions[turn - 1] if len(suggestions) >= turn else \
                FALLBACK_QUESTIONS[(turn - 1) % len(FALLBACK_QUESTIONS)]
            answer = await _post(client, "/guide/chat",
                                 chat_body(sample.exhibit_id, question, session_id, args),
                                 sample.exhibit_id, f"chat{turn}", collector, calls, steps, retries)
            if answer is None:
                failed += 1
                break
            session_id = answer.get("session_id")

        speech = await _post(client, "/speech", speech_body(story.get("text", ""), args),
                             sample.exhibit_id, "speech", collector, calls, steps, retries)
        if speech is None:
            failed += 1
            # Синтез не ответил — сам расход померить нечем, но объём работы
            # известен: в SpeechKit ушёл бы рассказ после нормализации чисел.
            # Считаем детерминированным нормализатором (тем же, что работает без
            # LLM) и помечаем как ОЦЕНКУ, чтобы её не спутали с замером.
            estimate = _estimated_tts_chars(story.get("text", ""))
            if estimate:
                estimates.append(estimate)
        if args.delay and index < len(samples):
            await asyncio.sleep(args.delay)
    return failed


async def run_live(args: argparse.Namespace) -> Tuple[List[Sample], List[Usage], List[Step], List[int], int]:
    """Прогон в этом же процессе: расход перехватывается из логов приложения."""
    import httpx

    from app.config import settings
    from app.db import SessionLocal
    from app.main import app as fastapi_app

    if not settings.llm_log_usage:
        print("ОШИБКА: LLM_LOG_USAGE=false — строк расхода не будет, мерить нечего.", file=sys.stderr)
        return [], [], [], [], 2

    async with SessionLocal() as session:
        samples = await _pick_exhibits(session, args.count, args.ids, args.min_description)
    if not samples:
        print("ОШИБКА: выборка пуста — проверьте --ids / --min-description и содержимое каталога.",
              file=sys.stderr)
        return [], [], [], [], 2

    _print_plan(samples, args)
    if not args.apply:
        return samples, [], [], [], 0
    if not settings.llm_configured:
        print("\nВНИМАНИЕ: LLM не настроен — ответы придут из стаба, строк расхода не будет.", file=sys.stderr)
    if not settings.tts_configured:
        print("ВНИМАНИЕ: SpeechKit не настроен — синтез стабовый, tts_request не пишется.", file=sys.stderr)

    collector = UsageCollector()
    root = logging.getLogger()
    root.addHandler(collector)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)

    calls: List[Usage] = []
    steps: List[Step] = []
    estimates: List[int] = []
    try:
        transport = httpx.ASGITransport(app=fastapi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://probe",
                                     timeout=args.timeout) as client:
            failed = await _run_scenario(client, samples, args, collector, calls, steps, estimates)
    finally:
        root.removeHandler(collector)

    for sample in samples:
        sample.calls = [c for c in calls if c.exhibit_id == sample.exhibit_id]
    return samples, calls, steps, estimates, 1 if failed else 0


def _print_plan(samples: List[Sample], args: argparse.Namespace) -> None:
    print(f"Выборка: {len(samples)} экспонатов")
    for sample in samples:
        size = f"{sample.description_chars:>5} зн." if sample.description_chars else "  нет описания"
        print(f"  id={sample.exhibit_id:<6} описание {size}  {sample.name[:60]}")
    planned = len(samples) * (1 + args.turns + 1)
    print(f"\nПлан: {len(samples)} рассказов + {len(samples) * args.turns} реплик чата + "
          f"{len(samples)} озвучек = {planned} запросов "
          f"(вызовов LLM больше: озвучка добавляет tts_spoken, вопросы-подсказки — только при промахе кэша).")
    if not args.apply:
        print("\nЭто сухой прогон, в облако не ходили. Чтобы померить — повторите с --apply.")


async def _remote_samples(client, args: argparse.Namespace) -> List[Sample]:
    """Выборка через публичный API стенда: равномерно по каталогу, с карточками.

    Карточку каждого кандидата всё равно приходится читать (в списке описания
    нет), зато это бесплатные запросы к БД — на счёт за облако они не влияют.
    """
    async def _get(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """GET с повторами: прод-шлюз отдаёт 502 на холодном инстансе (и не только)."""
        for attempt in range(args.retries + 1):
            try:
                response = await client.get(path, params=params)
            except Exception:  # noqa: BLE001 — сеть подождёт и повторит
                response = None
            if response is not None and response.status_code == 200:
                return response.json()
            if attempt < args.retries:
                await asyncio.sleep(1.0)
        return None

    async def _card(exhibit_id: int) -> Optional[Dict]:
        return await _get(f"/exhibits/{exhibit_id}")

    if args.ids:
        cards = [await _card(exhibit_id) for exhibit_id in args.ids]
        return [Sample(c["id"], c["name"], len(c.get("short_description") or ""))
                for c in cards if c]

    first = await _get("/exhibits", {"limit": 1, "offset": 0})
    total = (first or {}).get("total") or 0
    if not total:
        return []

    samples: List[Sample] = []
    taken: set = set()
    stride = max(1, total // args.count)
    for slot in range(args.count):
        # Кандидаты слота приезжают ОДНОЙ страницей: у карточки может не быть
        # описания (тогда мерили бы рассказ по названию, а не по данным музея),
        # и на каждого соседа отдельным запросом это стоило бы десятков вызовов
        # к шлюзу, который на холодном инстансе отдаёт 502.
        picked = False
        # Слот пробует несколько окон каталога: страница может не доехать (502 на
        # холодном инстансе), а в доехавшей — не оказаться ни одной карточки с
        # описанием нужной длины. Без этого запаса выборка молча худеет.
        for window in range(3):
            if picked:
                break
            offset = min(slot * stride + window * 8, max(0, total - 8))
            page = await _get("/exhibits", {"limit": 8, "offset": offset})
            for item in (page or {}).get("items", []):
                if item["id"] in taken:
                    continue
                card = await _card(item["id"])
                if not card or len(card.get("short_description") or "") < args.min_description:
                    continue
                taken.add(card["id"])
                samples.append(Sample(card["id"], card["name"], len(card["short_description"])))
                picked = True
                break
    return samples


async def run_remote(args: argparse.Namespace) -> Tuple[List[Sample], List[Usage], List[Step], List[int], int]:
    """Прогон по HTTP против стенда/прода; токены — из Cloud Logging после прогона."""
    import httpx

    base_url = args.base_url or os.environ.get("BASE_URL")
    if not base_url:
        print("ОШИБКА: для --source remote укажите --base-url (или BASE_URL).", file=sys.stderr)
        return [], [], [], [], 2
    if not args.log_group:
        print("ОШИБКА: нужен --log-group (имя или id группы Cloud Logging), иначе токены не забрать.",
              file=sys.stderr)
        return [], [], [], [], 2

    calls: List[Usage] = []
    steps: List[Step] = []
    estimates: List[int] = []
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=args.timeout) as client:
        samples = await _remote_samples(client, args)
        if not samples:
            print("ОШИБКА: выборка пуста — стенд не отдал каталог (проверьте GET /exhibits).",
                  file=sys.stderr)
            return [], [], [], [], 2
        _print_plan(samples, args)
        if not args.apply:
            return samples, [], [], [], 0

        started = time.time()
        failed = await _run_scenario(client, samples, args, None, calls, steps, estimates)
        finished = time.time()

    # Лог доезжает до Cloud Logging не мгновенно — даём ingestion фору и берём
    # окно с запасом с обеих сторон.
    await asyncio.sleep(args.log_wait)
    entries, problem = read_cloud_logs(args.log_group, started - 30, finished + args.log_wait + 60, args.yc)
    if problem:
        print(f"\nЛОГИ: {problem}", file=sys.stderr)
        return samples, calls, steps, estimates, 1
    attributed, orphans = attribute_by_time(entries, steps, args.log_slack)
    calls.extend(attributed)
    if orphans:
        print(f"\nВНИМАНИЕ: {orphans} строк расхода не попали ни в одно окно шага "
              f"(чужой трафик на стенде или расхождение часов) — в медианах они есть, "
              f"в разбивке по экспонатам их нет.", file=sys.stderr)
    for sample in samples:
        sample.calls = [c for c in calls if c.exhibit_id == sample.exhibit_id]
    return samples, calls, steps, estimates, 1 if failed else 0


# ── Выгрузка ─────────────────────────────────────────────────────────────────
CSV_COLUMNS = ["kind", "exhibit_id", "step", "operation", "model", "input_tokens", "output_tokens",
               "total_tokens", "chars", "duration_ms", "audio_bytes", "requests"]


def write_csv(path: str, calls: Sequence[Usage]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for call in calls:
            writer.writerow({k: v for k, v in asdict(call).items() if k in CSV_COLUMNS})


def write_json(path: str, payload: Dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Замер расхода LLM и SpeechKit на прогоне экспонатов.")
    parser.add_argument("--source", choices=("live", "remote", "log"), default="live",
                        help="live — прогон в этом процессе (нужны БД и ключи); "
                             "remote — прогон по HTTP против стенда, токены из Cloud Logging; "
                             "log — разобрать готовую выгрузку логов")
    parser.add_argument("log_file", nargs="?", help="файл логов для --source log ('-' — stdin)")
    parser.add_argument("--apply", action="store_true",
                        help="действительно вызывать LLM и синтез (по умолчанию сухой прогон)")
    parser.add_argument("--count", type=int, default=12, help="сколько экспонатов взять (по умолчанию 12)")
    parser.add_argument("--ids", type=lambda s: [int(p) for p in s.replace(" ", "").split(",") if p],
                        help="конкретные экспонаты через запятую (вместо автоматической выборки)")
    parser.add_argument("--turns", type=int, default=2, help="уточняющих вопросов на экспонат (по умолчанию 2)")
    parser.add_argument("--min-description", type=int, default=200,
                        help="брать карточки с описанием не короче N знаков (по умолчанию 200)")
    parser.add_argument("--style", default="engaging", help="стиль рассказа (engaging по умолчанию)")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--max-questions", type=int, default=4, help="сколько подсказок просить у ручек")
    parser.add_argument("--voice", default="alena")
    parser.add_argument("--audio-format", default="mp3", choices=("mp3", "ogg", "wav"))
    parser.add_argument("--delay", type=float, default=0.5, help="пауза между экспонатами, сек")
    parser.add_argument("--timeout", type=float, default=120.0, help="таймаут запроса, сек")
    parser.add_argument("--retries", type=int, default=2,
                        help="повторов на шаг: прод-шлюз отдаёт 502 на холодном инстансе")
    parser.add_argument("--base-url", help="адрес стенда для --source remote (или BASE_URL)")
    parser.add_argument("--log-group", help="группа Cloud Logging (имя или id) для --source remote")
    parser.add_argument("--yc", default="yc", help="путь к Yandex Cloud CLI (по умолчанию yc)")
    parser.add_argument("--log-wait", type=float, default=30.0,
                        help="пауза перед чтением логов, сек: ingestion не мгновенный")
    parser.add_argument("--log-slack", type=float, default=5.0,
                        help="запас окна шага при привязке строк лога, сек")
    parser.add_argument("--csv", help="куда сложить построчную выгрузку вызовов")
    parser.add_argument("--json", dest="json_path", help="куда сложить сводку и вызовы в JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    samples: List[Sample] = []
    estimates: List[int] = []
    if args.source == "log":
        if not args.log_file:
            print("ОШИБКА: для --source log укажите файл логов или '-' для stdin.", file=sys.stderr)
            return 2
        try:
            calls, steps = run_from_log(args.log_file)
        except OSError as exc:
            print(f"ОШИБКА: не читается файл логов: {exc}", file=sys.stderr)
            return 2
        exit_code = 0 if calls else 1
        title = f"РАСХОД ПО ЛОГАМ: {args.log_file}"
        if not calls:
            print("В выгрузке нет ни одной строки llm_usage/tts_request. "
                  "Проверьте период и что LOG_LEVEL=INFO на стенде.", file=sys.stderr)
    else:
        runner = run_remote if args.source == "remote" else run_live
        samples, calls, steps, estimates, exit_code = asyncio.run(runner(args))
        if exit_code == 2:
            return 2
        if not args.apply:
            return exit_code
        where = "стенд" if args.source == "remote" else "этот процесс"
        title = (f"РАСХОД НА ПРОГОНЕ ({where}): {len(samples)} экспонатов × "
                 f"(рассказ + {args.turns} вопроса + озвучка)")

    summary = summarize(calls, steps, estimates)
    if calls or estimates:
        print_report(summary, title)
    elif args.source in ("live", "remote"):
        # Прогон прошёл, а платных строк нет — почти всегда это стаб (нет ключей)
        # или задавленный уровень логирования, а не «модель ничего не стоила».
        print("\nСтрок расхода не собрано: проверьте ключи Yandex Cloud (GET /health → "
              "dependencies.llm/tts), LOG_LEVEL=INFO и LLM_LOG_USAGE.", file=sys.stderr)
        exit_code = exit_code or 1
        if steps:
            print_report(summary, title)

    if args.csv:
        write_csv(args.csv, calls)
        print(f"\nПострочно: {args.csv}")
    if args.json_path:
        write_json(args.json_path, {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": args.source,
            "exhibits": [
                {"exhibit_id": s.exhibit_id, "name": s.name, "description_chars": s.description_chars}
                for s in samples
            ],
            "calls": [asdict(c) for c in calls],
            "tts_chars_estimates": list(estimates),
            "steps": [asdict(s) for s in steps],
            "summary": summary,
        })
        print(f"Сводка: {args.json_path}")
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Уже сделанные вызовы оплачены, но их сводка потеряна — печатать
        # половину медианы хуже, чем не печатать: цифры уезжают в переписку.
        print("\nПрервано. Незавершённый прогон не считается.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 — трассировка asyncpg в лицо тут не нужна
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
