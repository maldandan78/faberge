"""Распознавание экспоната по фото (YOLO на Yandex Cloud + стаб)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import httpx

from ..config import settings
from . import UpstreamError


@dataclass
class RecognitionOutcome:
    recognized: bool
    label_slug: Optional[str]
    confidence: Optional[float]
    candidates: List[Tuple[str, float]] = field(default_factory=list)  # (label_slug, confidence)


async def recognize(
    image: bytes,
    known_slugs: Sequence[str],
    hall_id: Optional[int] = None,
    top_k: int = 3,
) -> RecognitionOutcome:
    """Вернуть label_slug для фото. `known_slugs` — классы из БД (для стаба)."""
    if settings.yolo_configured:
        return await _recognize_yandex(image, top_k)
    return _recognize_stub(image, known_slugs, top_k)


def _recognize_stub(image: bytes, known_slugs: Sequence[str], top_k: int) -> RecognitionOutcome:
    """Детерминированно «распознаёт» по хэшу картинки среди известных классов."""
    if not known_slugs:
        return RecognitionOutcome(False, None, 0.0, [])
    h = int(hashlib.sha256(image).hexdigest(), 16)
    confidence = round(0.45 + (h % 55) / 100.0, 2)  # 0.45..0.99
    idx = h % len(known_slugs)
    primary = known_slugs[idx]
    if confidence >= settings.recognition_confidence_threshold:
        return RecognitionOutcome(True, primary, confidence, [(primary, confidence)])
    candidates: List[Tuple[str, float]] = []
    for i in range(min(top_k, len(known_slugs))):
        candidates.append((known_slugs[(idx + i) % len(known_slugs)], round(max(0.05, confidence - i * 0.08), 2)))
    return RecognitionOutcome(False, None, confidence, candidates)


async def _recognize_yandex(image: bytes, top_k: int) -> RecognitionOutcome:
    """Реальный вызов развёрнутой YOLO.

    Ожидаемый ответ эндпоинта (контракт деплоя ML):
        {"label_slug": "faberge_egg_winter", "confidence": 0.93,
         "candidates": [{"label_slug": "...", "confidence": 0.4}, ...]}
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                settings.yolo_endpoint,  # type: ignore[arg-type]
                headers={"Authorization": f"Api-Key {settings.yandex_api_key}"},
                files={"file": ("photo.jpg", image, "application/octet-stream")},
                params={"top_k": top_k},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise UpstreamError("Сервис распознавания временно недоступен.") from exc

    confidence = data.get("confidence")
    label_slug = data.get("label_slug")
    candidates = [
        (c["label_slug"], float(c["confidence"]))
        for c in data.get("candidates", [])
        if "label_slug" in c
    ]
    recognized = bool(label_slug) and (confidence or 0) >= settings.recognition_confidence_threshold
    return RecognitionOutcome(recognized, label_slug if recognized else None, confidence, candidates)
