"""Синтез речи (Yandex SpeechKit + стаб).

Стаб генерирует настоящий (тихий) WAV нужной длительности и кладёт его в
media/tts/, чтобы кнопка «Прослушать» работала локально без облака. Реальный
SpeechKit вызывается при наличии ключа и отдаёт mp3/oggopus.
"""
from __future__ import annotations

import hashlib
import os
import wave
from dataclasses import dataclass
from typing import Optional

import httpx

from ..config import settings
from . import UpstreamError

SPEECHKIT_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
_CHARS_PER_SEC = 14.0  # грубая оценка темпа речи


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
    emotion: str = "neutral",
) -> SpeechOutcome:
    characters = len(text)
    if settings.tts_configured:
        return await _synthesize_yandex(text, voice, fmt, speed, emotion, characters)
    return _synthesize_stub(text, voice, characters)


def _synthesize_stub(text: str, voice: str, characters: int) -> SpeechOutcome:
    seconds = max(1.0, min(characters / _CHARS_PER_SEC, 12.0))  # ограничим файл 12 сек
    key = hashlib.sha256(f"{voice}:{text}".encode("utf-8")).hexdigest()[:16]
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
    audio_format = "oggopus" if fmt == "oggopus" else ("lpcm" if fmt == "wav" else "mp3")
    data = {
        "text": text,
        "voice": voice,
        "emotion": emotion,
        "speed": str(speed),
        "format": audio_format,
        "lang": "ru-RU",
    }
    if settings.yandex_folder_id:
        data["folderId"] = settings.yandex_folder_id
    headers = {"Authorization": f"Api-Key {settings.speechkit_api_key or settings.yandex_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(SPEECHKIT_URL, headers=headers, data=data)
            resp.raise_for_status()
            audio_bytes = resp.content
    except Exception as exc:  # noqa: BLE001
        raise UpstreamError("Сервис озвучивания временно недоступен.") from exc

    # Кэшируем результат в Object Storage в проде; локально — в media/.
    key = hashlib.sha256(f"{voice}:{text}".encode("utf-8")).hexdigest()[:16]
    rel = f"tts/{voice}_{key}.{fmt}"
    out_dir = os.path.join(settings.media_dir, "tts")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(settings.media_dir, rel), "wb") as fh:
        fh.write(audio_bytes)
    seconds = max(1.0, characters / _CHARS_PER_SEC)
    return SpeechOutcome(
        audio_url=f"{settings.public_base_url}/media/{rel}",
        fmt=fmt,
        duration_ms=int(seconds * 1000),
        characters=characters,
        cached=False,
    )
