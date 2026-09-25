"""Синтез речи (Yandex SpeechKit + стаб).

Стаб генерирует настоящий (тихий) WAV нужной длительности и кладёт его в
media/tts/, чтобы кнопка «Прослушать» работала локально без облака. Реальный
SpeechKit вызывается при наличии ключа и отдаёт mp3/oggopus.

Версий API две. По умолчанию — v3 (`/tts/v3/utteranceSynthesis`): она
тарифицируется по запросам, а не по символам, и возвращает аудио потоком
JSON-кусков с таймингами. v1 (`/speech/v1/tts:synthesize`) остаётся рабочей и
включается SPEECHKIT_API_VERSION=v1 — это откат на случай, если с v3 что-то
пойдёт не так на проде.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import wave
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

import httpx

from ..config import settings
from . import UpstreamError, llm, storage
from .text_normalize import has_numerals, normalize_for_tts

logger = logging.getLogger(__name__)

# API v1 тарифицируется по СИМВОЛАМ, v3 — по ЗАПРОСАМ. У нас запросы короткие
# (реплика гида, подпись экспоната), поэтому по умолчанию идёт v3; v1 остаётся
# рабочим путём и включается SPEECHKIT_API_VERSION=v1 (аварийный откат).
SPEECHKIT_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
SPEECHKIT_V3_URL = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
_CHARS_PER_SEC = 14.0  # грубая оценка темпа речи (фолбэк, если v3 не вернул тайминги)
_CONTENT_TYPE = {"mp3": "audio/mpeg", "oggopus": "audio/ogg", "wav": "audio/wav"}
# Контейнер аудио в v3 задаётся перечислением, а не строкой формата из v1.
_V3_CONTAINER = {"mp3": "MP3", "oggopus": "OGG_OPUS", "wav": "WAV"}

# Предел длины ОДНОГО запроса v3 — документированный: «250 символов и 24 секунды
# на синтезируемую фразу». Замер на проде 02.09.2026 совпал с документацией с
# точностью до знака: 249 синтезируется, 250 — стабильный отказ (быстрый, ~300 мс,
# то есть ошибка сервиса, а не таймаут). Наружу это выглядело как «Сервис
# озвучивания временно недоступен» на КАЖДОМ рассказе гида: рассказ у нас 300–600
# знаков, то есть с переезда на v3 (19.08.2026) кнопка «Прослушать» под рассказом
# не работала вовсе, а короткие подписи работали — потому баг и не был виден.
# Число вынесено в настройку на случай, если предел сервиса изменится.
_V3_LIMIT_FALLBACK = 249
# Вторая половина предела — 24 секунды звука на фразу. По знакам мы в него
# укладываемся (249 знаков ≈ 18 с в темпе 1.0), но на замедленной речи — уже нет,
# поэтому на speed < 1 предел по знакам ужимается пропорционально.
_V3_MAX_SECONDS = 24.0

_SENTENCE_RE = re.compile(r"[^.!?…]+(?:[.!?…]+|$)")


def v3_chunk_limit() -> int:
    return getattr(settings, "speechkit_v3_max_chars", None) or _V3_LIMIT_FALLBACK


def split_for_v3(text: str, limit: Optional[int] = None) -> List[str]:
    """Разбить текст на куски не длиннее предела, по границам предложений.

    Рвать на полуслове нельзя: синтез читает кусок как самостоятельную фразу, и
    интонация на обрыве слышна. Поэтому режем по предложениям, а слишком длинное
    предложение — по словам (и только совсем уж длинное «слово» — жёстко).
    """
    limit = limit or v3_chunk_limit()
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []

    pieces: List[str] = []
    for sentence in (m.group(0).strip() for m in _SENTENCE_RE.finditer(text)):
        if not sentence:
            continue
        if len(sentence) <= limit:
            pieces.append(sentence)
            continue
        current = ""
        for word in sentence.split():
            while len(word) > limit:            # одно «слово» длиннее предела
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(word[:limit])
                word = word[limit:]
            candidate = f"{current} {word}".strip()
            if len(candidate) > limit:
                pieces.append(current)
                current = word
            else:
                current = candidate
        if current:
            pieces.append(current)

    chunks: List[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + 1 + len(piece) <= limit:
            chunks[-1] = f"{chunks[-1]} {piece}"
        else:
            chunks.append(piece)
    return chunks


# Поддерживаемые амплуа (роли) по голосам. В v1 REST параметр называется
# `emotion`, но принимает именно значения амплуа из «Списка голосов» SpeechKit.
# Нейтральное амплуа звучит «по-роботски»; тёплое (good/friendly) — человечнее.
# Если запросить амплуа, которого у голоса нет, SpeechKit отвечает ошибкой,
# поэтому здесь же — карта для безопасного фолбэка.
VOICE_ROLES = {
    "alena": {"neutral", "good"},
    "filipp": {"neutral"},
    "ermil": {"neutral", "good"},
    "jane": {"neutral", "good", "evil"},
    "omazh": {"neutral", "evil"},
    "zahar": {"neutral", "good"},
    "dasha": {"neutral", "good", "friendly"},
    "lera": {"neutral", "friendly"},
    "marina": {"neutral", "whisper", "friendly"},
    "alexander": {"neutral", "good"},
    "kirill": {"neutral", "strict", "good"},
}
# Приоритет «живости» при фолбэке: тёплое → дружелюбное → нейтральное.
_WARM_PRIORITY = ("good", "friendly", "neutral")


def _resolve_role(voice: str, requested: str) -> str:
    """Подбирает ближайшее поддерживаемое голосом амплуа к запрошенному."""
    supported = VOICE_ROLES.get(voice, {"neutral"})
    if requested in supported:
        return requested
    for role in _WARM_PRIORITY:
        if role in supported:
            return role
    return "neutral"


def _cache_key(voice: str, text: str, role: str, speed: float, fmt: str) -> str:
    raw = f"{voice}:{role}:{speed}:{fmt}:{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── Числительные прописью перед синтезом ─────────────────────────────────────
# Баг-репорт 28.07.2026, п.2: «Пётр I» уходил в синтез как «Пётр 1» и звучал
# «Пётр один». Правильную форму («Пётр Первый», «в девятнадцатом веке») даёт
# llm.to_spoken_text — тот же инструмент, что готовит short_description_spoken
# у экспонатов (E15). Здесь он подключён и к произвольному тексту (кнопка
# «Прослушать» в чате), а детерминированный normalize_for_tts остаётся фолбэком.
#
# Стоимость: LLM зовём только когда в тексте реально есть числа, и кэшируем
# результат по хэшу исходного текста — повторные «Прослушать» на том же ответе
# гида и типовые фразы не оплачиваются заново. Кэш процессный (LRU): при
# рестарте/масштабировании просто прогревается заново.
_SPOKEN_CACHE: "OrderedDict[str, str]" = OrderedDict()
_SPOKEN_CACHE_MAX = 512
# Защита от «разговорчивой» модели: если LLM вернул явно не переписанный текст
# (пусто или втрое длиннее исходного), берём детерминированный вариант.
_SPOKEN_MAX_GROWTH = 3.0


async def prepare_for_tts(text: str) -> str:
    """Подготовить произвольный текст к синтезу: числа — прописью, в нужном падеже."""
    if not text or not has_numerals(text):
        return text
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cached = _SPOKEN_CACHE.get(key)
    if cached is not None:
        _SPOKEN_CACHE.move_to_end(key)
        return cached
    spoken = None
    if settings.tts_spoken_via_llm:
        # to_spoken_text сам возвращает None, если LLM не настроен или недоступен.
        spoken = await llm.to_spoken_text(text)
        if spoken and len(spoken) > len(text) * _SPOKEN_MAX_GROWTH:
            spoken = None
    result = spoken or normalize_for_tts(text)
    _SPOKEN_CACHE[key] = result
    if len(_SPOKEN_CACHE) > _SPOKEN_CACHE_MAX:
        _SPOKEN_CACHE.popitem(last=False)
    return result


@dataclass
class SpeechOutcome:
    audio_url: str
    fmt: str
    duration_ms: int
    characters: int
    cached: bool


async def synthesize(
    text: str,
    voice: str = "alena",
    fmt: str = "mp3",
    speed: float = 1.0,
    emotion: str = "good",
) -> SpeechOutcome:
    # Числа — прописью в нужном падеже («Пётр I» → «Пётр Первый», «XIX век» →
    # «девятнадцатый век»). Делаем ДО подсчёта символов и кэш-ключа — иначе на
    # старые записи кэша отдавалась бы прежняя (неправильная) озвучка.
    text = await prepare_for_tts(text)
    characters = len(text)
    if settings.tts_configured:
        return await _synthesize_yandex(text, voice, fmt, speed, emotion, characters)
    return _synthesize_stub(text, voice, characters)


def _synthesize_stub(text: str, voice: str, characters: int) -> SpeechOutcome:
    seconds = max(1.0, min(characters / _CHARS_PER_SEC, 12.0))  # ограничим файл 12 сек
    key = _cache_key(voice, text, "stub", 1.0, "wav")
    rel = f"tts/{voice}_{key}.wav"
    out_dir = os.path.join(settings.media_dir, "tts")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(settings.media_dir, rel)
    cached = os.path.exists(path)
    if not cached:
        _write_silent_wav(path, seconds)
    return SpeechOutcome(
        audio_url=f"{settings.public_base_url}/media/{rel}",
        fmt="wav",
        duration_ms=int(seconds * 1000),
        characters=characters,
        cached=cached,
    )


def _write_silent_wav(path: str, seconds: float, rate: int = 8000) -> None:
    frames = int(seconds * rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)


async def _synthesize_yandex(
    text: str, voice: str, fmt: str, speed: float, emotion: str, characters: int
) -> SpeechOutcome:
    # `emotion` несёт амплуа голоса (в v1 параметр так и называется, в v3 это
    # hint `role`); приводим к поддерживаемому, чтобы тёплый дефолт (good) не
    # ронял синтез на голосах, у которых его нет.
    role = _resolve_role(voice, emotion)
    duration_ms: Optional[int] = None
    requests = 1
    if settings.speechkit_v3:
        audio_bytes, duration_ms, requests = await _fetch_v3(text, voice, fmt, speed, role)
    else:
        audio_bytes = await _fetch_v1(text, voice, fmt, speed, role)
    if duration_ms is None:
        duration_ms = int(max(1.0, characters / _CHARS_PER_SEC) * 1000)

    # Кэшируем результат в Object Storage в проде (ссылка переживает смену
    # экземпляра функции); локально, без бакета, — в media/. Ключ включает
    # амплуа/скорость/формат, иначе смена настроек отдавала бы старый файл.
    key = _cache_key(voice, text, role, speed, fmt)
    rel = f"tts/{voice}_{key}.{fmt}"
    if settings.storage_configured:
        stored = await storage.save_bytes(
            audio_bytes, rel, _CONTENT_TYPE.get(fmt, "application/octet-stream")
        )
        audio_url = stored.url
    else:
        out_dir = os.path.join(settings.media_dir, "tts")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(settings.media_dir, rel), "wb") as fh:
            fh.write(audio_bytes)
        audio_url = f"{settings.public_base_url}/media/{rel}"
    # Строка расхода на синтез. В v3 тарификация по ЗАПРОСАМ, поэтому в логе
    # важно и число символов (чтобы видеть, что мы не шлём простыни), и сам факт
    # запроса: одна строка = один платный вызов.
    # `requests` — сколько ПЛАТНЫХ вызовов ушло: в v3 длинный текст режется на
    # куски, и одна строка лога больше не равна одному запросу. Считать расход
    # по числу строк, как раньше, теперь нельзя — отсюда отдельное поле.
    logger.info(
        "tts_request api=%s voice=%s role=%s fmt=%s chars=%s duration_ms=%s bytes=%s requests=%s",
        "v3" if settings.speechkit_v3 else "v1",
        voice, role, fmt, characters, duration_ms, len(audio_bytes), requests,
    )
    return SpeechOutcome(
        audio_url=audio_url,
        fmt=fmt,
        duration_ms=duration_ms,
        characters=characters,
        cached=False,
    )


def _auth_headers(with_folder: bool = True) -> dict:
    """Заголовки запроса. В v1 каталог передаётся полем folderId в теле, в v3 —
    заголовком x-folder-id, поэтому заголовок ставим только там, где он нужен."""
    headers = {"Authorization": f"Api-Key {settings.speechkit_api_key or settings.yandex_api_key}"}
    if with_folder and settings.yandex_folder_id:
        headers["x-folder-id"] = settings.yandex_folder_id
    return headers


def _log_synthesis_failure(api: str, exc: Exception) -> None:
    """Записать ПРИЧИНУ провала синтеза: наружу-то уходит одна общая фраза.

    Замер расхода 02.09.2026 поймал на проде 36 подряд ответов 502 «Сервис
    озвучивания временно недоступен», а в логах функции про них не было ни
    строки: обе ветки (`_fetch_v1`/`_fetch_v3`) заворачивали любое исключение в
    UpstreamError молча. Отличить «SpeechKit ответил 403» от «не резолвится
    хост» снаружи невозможно, а решения это требует разных. Тело ответа берём
    коротким куском — в нём лежит сообщение Yandex, ради которого всё и
    затевалось; заголовки (там ключ) не логируем никогда.
    """
    detail = str(exc)[:200].replace("\n", " ")
    status = ""
    response = getattr(exc, "response", None)
    if response is not None:
        status = f" status={getattr(response, 'status_code', '-')}"
        body = (getattr(response, "text", "") or "")[:300].replace("\n", " ")
        detail = f"{detail} body={body}"
    logger.warning("tts_failed api=%s error=%s%s detail=%s", api, type(exc).__name__, status, detail)


async def _fetch_v1(text: str, voice: str, fmt: str, speed: float, role: str) -> bytes:
    """Синтез через API v1 (тарификация по символам). Аварийный путь."""
    audio_format = "oggopus" if fmt == "oggopus" else ("lpcm" if fmt == "wav" else "mp3")
    data = {
        "text": text,
        "voice": voice,
        "emotion": role,
        "speed": str(speed),
        "format": audio_format,
        "lang": "ru-RU",
    }
    # lpcm/oggopus отдаём в 48 кГц — иначе wav скатывается к «телефонному»,
    # роботному звучанию. Для mp3 частота фиксирована и параметр игнорируется.
    if audio_format in ("lpcm", "oggopus"):
        data["sampleRateHertz"] = "48000"
    if settings.yandex_folder_id:
        data["folderId"] = settings.yandex_folder_id
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(SPEECHKIT_URL, headers=_auth_headers(with_folder=False), data=data)
            resp.raise_for_status()
            return resp.content
    except Exception as exc:  # noqa: BLE001
        _log_synthesis_failure("v1", exc)
        raise UpstreamError("Сервис озвучивания временно недоступен.") from exc


def _v3_payload(text: str, voice: str, fmt: str, speed: float, role: str,
                unsafe_mode: bool = False) -> dict:
    """Тело запроса v3.

    Отличия от v1, из-за которых понадобился отдельный путь: параметры голоса
    переехали в список `hints` (по одному полю в элементе — в proto это oneof),
    формат задаётся перечислением контейнера, а не строкой, и добавилась
    нормализация громкости (LUFS — рекомендация SpeechKit, ровнее по громкости
    между репликами).
    """
    hints: List[dict] = [{"voice": voice}, {"role": role}]
    if speed and speed != 1.0:
        hints.append({"speed": float(speed)})
    payload = {
        "text": text,
        "hints": hints,
        "outputAudioSpec": {"containerAudio": {"containerAudioType": _V3_CONTAINER.get(fmt, "MP3")}},
        "loudnessNormalizationType": "LUFS",
    }
    if unsafe_mode:
        # Штатная опция сервиса: «Automatically split long text to several
        # utterances and bill accordingly. Some degradation in service quality is
        # possible» (proto UtteranceSynthesisRequest.unsafe_mode). Деньги те же,
        # что при нашем разбиении — платят за фразы; выигрыш в том, что ответ
        # приходит ОДНИМ потоком, то есть контейнер собирает сам SpeechKit.
        # Поэтому она нужна там, где склеить куски нельзя: wav/ogg.
        payload["unsafeMode"] = True
    return payload


def _iter_v3_messages(body: str) -> Iterator[dict]:
    """Сообщения ответа v3: по одному JSON на строку либо один цельный JSON.

    Обычный ответ — поток строк, но короткий синтез умещается в одно сообщение,
    и посредники (API Gateway) отдают его как обычный JSON-объект или массив.
    Разбираем оба вида, иначе аудио «пропадёт» на ровном месте.
    """
    body = (body or "").strip()
    if not body:
        return
    try:
        whole = json.loads(body)
    except json.JSONDecodeError:
        pass
    else:
        for message in (whole if isinstance(whole, list) else [whole]):
            if isinstance(message, dict):
                yield message
        return
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            yield message


def _parse_v3_stream(body: str) -> Tuple[bytes, Optional[int]]:
    """Собрать аудио из потокового ответа v3.

    v3 отвечает не одним JSON, а ПОТОКОМ объектов `{"result": {...}}` — по
    одному на кусок аудио; куски идут подряд и склеиваются в готовый файл.
    Тайминги (`startMs`/`lengthMs`) приходят там же — берём длительность из
    них, а не из оценки по числу символов.
    """
    chunks: List[bytes] = []
    duration_ms = 0
    for message in _iter_v3_messages(body):
        result = message.get("result") if isinstance(message, dict) else None
        if not isinstance(result, dict):
            continue
        data = (result.get("audioChunk") or {}).get("data")
        if data:
            chunks.append(base64.b64decode(data))
        # int64 в JSON приходит строкой ("lengthMs": "1234").
        try:
            end = int(result.get("startMs") or 0) + int(result.get("lengthMs") or 0)
            duration_ms = max(duration_ms, end)
        except (TypeError, ValueError):
            pass
    return b"".join(chunks), (duration_ms or None)


async def _fetch_v3(
    text: str, voice: str, fmt: str, speed: float, role: str
) -> Tuple[bytes, Optional[int], int]:
    """Синтез через API v3. Возвращает (аудио, длительность, число запросов).

    Длинный текст (сверх документированных 250 знаков / 24 с на фразу) идёт
    двумя разными путями, и разница не в цене — платят в обоих случаях за фразы:

    - mp3 — НАШИМ разбиением по границам предложений: куски склеиваются
      конкатенацией кадров, и мы сами решаем, где рвать. Пауза приходится на
      конец предложения, а не на середину придаточного;
    - wav/ogg — штатным `unsafe_mode`: их куски склеивать нельзя (у каждого свой
      заголовок/поток), а сервис отдаёт цельный контейнер. Если и это не вышло —
      откат на v1, у которого предел на порядок выше.
    """
    limit = v3_chunk_limit()
    if speed and speed < 1.0:
        # 24 секунды на фразу — вторая половина предела; на замедленной речи в
        # неё упирается более короткий текст.
        limit = max(1, int(limit * speed))
    chunks = split_for_v3(text, limit)
    if len(chunks) > 1:
        if fmt != "mp3":
            try:
                audio, duration_ms = await _fetch_v3_once(text, voice, fmt, speed, role, unsafe_mode=True)
                return audio, duration_ms, len(chunks)
            except UpstreamError:
                return await _fetch_v1(text, voice, fmt, speed, role), None, 1
        audio = b""
        total_ms = 0
        known_duration = False
        for chunk in chunks:
            part, duration_ms = await _fetch_v3_once(chunk, voice, fmt, speed, role)
            audio += part
            if duration_ms:
                total_ms += duration_ms
                known_duration = True
        return audio, (total_ms if known_duration else None), len(chunks)
    audio, duration_ms = await _fetch_v3_once(chunks[0] if chunks else text, voice, fmt, speed, role)
    return audio, duration_ms, 1


async def _fetch_v3_once(
    text: str, voice: str, fmt: str, speed: float, role: str, unsafe_mode: bool = False
) -> Tuple[bytes, Optional[int]]:
    """Один HTTP-запрос к v3. С `unsafe_mode` сервис сам режет длинный текст."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                SPEECHKIT_V3_URL, headers=_auth_headers(),
                json=_v3_payload(text, voice, fmt, speed, role, unsafe_mode)
            )
            resp.raise_for_status()
            audio_bytes, duration_ms = _parse_v3_stream(resp.text)
    except UpstreamError:
        raise
    except Exception as exc:  # noqa: BLE001
        _log_synthesis_failure("v3", exc)
        raise UpstreamError("Сервис озвучивания временно недоступен.") from exc
    if not audio_bytes:
        # 200 без единого audioChunk — ошибка формата запроса или пустой ответ.
        # Молча отдавать «файл» на 0 байт нельзя: фронт покажет битый плеер.
        logger.warning("speechkit v3: пустой ответ, voice=%s fmt=%s chars=%s", voice, fmt, len(text))
        raise UpstreamError("Сервис озвучивания временно недоступен.")
    return audio_bytes, duration_ms
