"""Распознавание экспоната по фото (внешний сервис поиска YOLO+DINOv2 + стаб)."""
from __future__ import annotations

import difflib
import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Collection, Dict, List, Mapping, Optional, Sequence, Tuple

import httpx

from ..config import settings
from . import UpstreamError

logger = logging.getLogger(__name__)


@dataclass
class RecognitionOutcome:
    recognized: bool
    label_slug: Optional[str]
    confidence: Optional[float]
    candidates: List[Tuple[str, float]] = field(default_factory=list)  # (label_slug, confidence)
    # Предсказания ML-сервиса, которые не удалось сшить с каталогом:
    # (title, confidence). Роутер добирает по ним кандидатов полнотекстовым
    # поиском, чтобы при неудаче фронт показал топ-3, а не глухую ошибку (E19).
    # title — русское название, если сервис его прислал (старый контракт); по
    # контракту 1.0.0 его нет, тогда строка пустая и добор не выполняется.
    unmatched: List[Tuple[str, float]] = field(default_factory=list)


# ── Сшивка названий ML-индекса с каталогом ───────────────────────────────────
# Фолбэк для старого контракта сервиса поиска, который ключевал предметы по
# русскому названию (title), а не по slug'у (см. `match_slug` ниже). Названия приходят из другого источника, поэтому расходятся в мелочах: регистр,
# «ё/е», кавычки-ёлочки против прямых, двойные пробелы, хвостовая пунктуация. При
# точном сравнении такое предсказание молча выбрасывалось и распознавание «не
# работало» при полностью исправной модели (баг-репорт 28.07.2026, п.1).
_QUOTES = "«»„“”\"'`’‘"
_PUNCT_EDGE_RE = re.compile(r"^[\s\-–—.,;:!?]+|[\s\-–—.,;:!?]+$")
_SPACES_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Ключ для сопоставления названий: регистр, «ё», кавычки и пробелы не важны."""
    text = unicodedata.normalize("NFKC", name)
    text = "".join(" " if ch in _QUOTES else ch for ch in text)
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = _SPACES_RE.sub(" ", text).strip().casefold()
    return _PUNCT_EDGE_RE.sub("", text)


def build_name_index(name_to_slug: Mapping[str, str]) -> Dict[str, str]:
    """Карта нормализованное имя → label_slug (обе стороны нормализуются одинаково)."""
    index: Dict[str, str] = {}
    for name, slug in name_to_slug.items():
        key = normalize_name(name or "")
        if key and key not in index:
            index[key] = slug
    return index


def match_title(
    title: str, index: Mapping[str, str], cutoff: Optional[float] = None
) -> Tuple[Optional[str], str]:
    """Найти label_slug по названию из ML-индекса.

    Возвращает ``(slug, способ)``: ``exact`` — совпали нормализованные ключи,
    ``fuzzy`` — сошлись с точностью не ниже ``cutoff``, ``miss`` — не нашли.
    Нечёткое сопоставление добирает расхождения, которые нормализация не лечит
    (сокращения, «яйцо Ландыши» vs «Яйцо „Ландыши“»).
    """
    key = normalize_name(title or "")
    if not key:
        return None, "miss"
    slug = index.get(key)
    if slug is not None:
        return slug, "exact"
    threshold = settings.recognition_name_match_cutoff if cutoff is None else cutoff
    if threshold <= 0:
        return None, "miss"
    close = difflib.get_close_matches(key, list(index.keys()), n=1, cutoff=threshold)
    if close:
        return index[close[0]], "fuzzy"
    return None, "miss"


# ── Сшивка slug'ов ML-индекса с каталогом ────────────────────────────────────
# С контракта Faberge Search API 1.0.0 сервис отдаёт ``title_en`` — slug из URL
# страницы предмета на сайте музея (``paskhalnoye-yaytso-kurochka``). Наш
# label_slug в большинстве карточек — тот же slug, но не во всех: у ключевых яиц
# он с префиксом и подчёркиваниями (``faberge_paskhalnoye_yaytso_landyshi``),
# часть заведена другой транслитерацией (``pasxalnoe_yajczo`` против
# ``paskhalnoe-yaytso``), длинные обрезаны до 100 знаков с хвостом-хэшем
# (load_faberge.clamp_slug). Поэтому сравниваем не строки, а канонические ключи.
_SLUG_MAX = 100
_SLUG_CLAMPED_RE = re.compile(r"^.{91}-[0-9a-f]{8}$")
_SLUG_SEP_RE = re.compile(r"[^a-z0-9]+")
_SLUG_PREFIX = "faberge-"
# Свёртка вариантов транслитерации к одному написанию. Порядок важен: сначала
# диграфы, потом одиночные буквы.
_TRANSLIT_FOLD = (
    ("shch", "sch"), ("shh", "sch"),     # щ
    ("kh", "x"),                          # х: kh / x
    ("cz", "ts"), ("tz", "ts"),           # ц: cz / tz / ts
    ("j", "y"), ("yy", "y"),              # й/я/ю: j / y, «ый» → yj → yy
    ("oye", "oe"), ("iye", "ie"),         # окончания -ое/-ие: oye / oe
)
# «ы»/«ый» в конце слова: chasyi / chasy, prezentatsionnyij / prezentatsionnyy.
_SLUG_END_YI_RE = re.compile(r"(?:yiy|yi|iy)(?=-|$)")
_DIGITS_RE = re.compile(r"\d+")


def clamp_slug(slug: str) -> str:
    """Как load_faberge.clamp_slug: так длинный slug музея лёг в VARCHAR(100)."""
    if len(slug) <= _SLUG_MAX:
        return slug
    return slug[:91] + "-" + hashlib.sha1(slug.encode()).hexdigest()[:8]


def normalize_slug(slug: str) -> str:
    """Канонический ключ slug'а: регистр, разделители, префикс и транслит не важны."""
    text = (slug or "").strip().casefold().replace("'", "").replace("`", "")
    text = _SLUG_SEP_RE.sub("-", text).strip("-")
    if text.startswith(_SLUG_PREFIX):
        text = text[len(_SLUG_PREFIX):]
    for src, dst in _TRANSLIT_FOLD:
        text = text.replace(src, dst)
    return _SLUG_END_YI_RE.sub("y", text)


def build_slug_index(known_slugs: Sequence[str]) -> Dict[str, str]:
    """Карта канонический ключ → label_slug. Обрезанные slug'и (с хвостом-хэшем)
    в карту не кладём: их ключ бессмыслен, они сшиваются через `clamp_slug`."""
    index: Dict[str, str] = {}
    for slug in known_slugs:
        if not slug or _SLUG_CLAMPED_RE.match(slug):
            continue
        key = normalize_slug(slug)
        if key and key not in index:
            index[key] = slug
    return index


def match_slug(
    title_en: str,
    index: Mapping[str, str],
    known_slugs: Collection[str],
    cutoff: Optional[float] = None,
) -> Tuple[Optional[str], str]:
    """Найти наш label_slug по ``title_en`` из ML-индекса.

    Возвращает ``(slug, способ)``: ``exact`` — строка совпала с label_slug (в том
    числе после обрезки до 100 знаков), ``normalized`` — совпали канонические
    ключи, ``fuzzy`` — сошлись с точностью не ниже ``cutoff``, ``miss`` — нет.
    Нечёткое совпадение требует одинаковых первого слова и чисел в slug'ах.
    Первое слово — тип предмета, а хвост у разных предметов бывает общий и
    длинный (``blyudo-s-monogrammami-imperatora-…`` / ``byuvar-s-monogrammami-
    imperatora-…``). Номером музей различает одноимённые (``chasy`` /
    ``chasy-2``), и ``chasy-2`` → ``chasy-3`` было бы ошибкой, а не опечаткой.
    """
    raw = (title_en or "").strip()
    if not raw:
        return None, "miss"
    for candidate in (raw, clamp_slug(raw)):
        if candidate in known_slugs:
            return candidate, "exact"
    key = normalize_slug(raw)
    if not key:
        return None, "miss"
    slug = index.get(key)
    if slug is not None:
        return slug, "normalized"
    threshold = settings.recognition_slug_match_cutoff if cutoff is None else cutoff
    if threshold <= 0:
        return None, "miss"
    head, digits = key.split("-", 1)[0], _DIGITS_RE.findall(key)
    for close in difflib.get_close_matches(key, list(index.keys()), n=5, cutoff=threshold):
        if close.split("-", 1)[0] == head and _DIGITS_RE.findall(close) == digits:
            return index[close], "fuzzy"
    return None, "miss"


async def recognize(
    image: bytes,
    known_slugs: Sequence[str],
    hall_id: Optional[int] = None,
    top_k: int = 3,
    name_to_slug: Optional[Mapping[str, str]] = None,
) -> RecognitionOutcome:
    """Вернуть label_slug для фото.

    `known_slugs` — классы из БД: для стаба и для сшивки ``title_en`` ML-поиска.
    `name_to_slug` — карта имя→label_slug, фолбэк для старого контракта (``title``).
    """
    if settings.yolo_configured:
        return await _recognize_search(image, name_to_slug or {}, known_slugs, top_k)
    return _recognize_stub(image, known_slugs, top_k)


def _recognize_stub(image: bytes, known_slugs: Sequence[str], top_k: int) -> RecognitionOutcome:
    """Детерминированно «распознаёт» по хэшу картинки среди известных классов."""
    if not known_slugs:
        return RecognitionOutcome(False, None, 0.0, [])
    h = int(hashlib.sha256(image).hexdigest(), 16)
    confidence = round(0.45 + (h % 55) / 100.0, 2)  # 0.45..0.99
    idx = h % len(known_slugs)
    primary = known_slugs[idx]
    # Список кандидатов строим всегда — и при уверенном ответе тоже: следующие по
    # вероятности варианты нужны фронту, чтобы показать «другие варианты» рядом с
    # найденным. Реальный ML-адаптер ведёт себя так же, стаб не должен отличаться
    # формой ответа, иначе экран, отлаженный на стабе, на проде выглядит иначе.
    candidates: List[Tuple[str, float]] = [
        (known_slugs[(idx + i) % len(known_slugs)], round(max(0.05, confidence - i * 0.08), 2))
        for i in range(min(top_k, len(known_slugs)))
    ]
    recognized = confidence >= settings.recognition_confidence_threshold
    return RecognitionOutcome(
        recognized, primary if recognized else None, confidence, candidates
    )


async def _recognize_search(
    image: bytes, name_to_slug: Mapping[str, str], known_slugs: Sequence[str], top_k: int
) -> RecognitionOutcome:
    """Реальный вызов развёрнутого сервиса поиска по фото (YOLO + DINOv2).

    Контракт ``POST {yolo_endpoint}`` (Faberge Search API 1.0.0 ``/search``):
        multipart {file, limit} →
        {"predictions": [{"item_id", "title_en", "confidence"}, ...], "found": bool}

    ``title_en`` — slug страницы предмета на сайте музея, ``item_id`` — внутренний
    id ML-сервиса (с нашими id не связан). Сшиваем ``title_en → label_slug``
    через `match_slug`. Если ``title_en`` нет или он не сшился, а сервис прислал
    ``title`` (контракт до 1.0.0), — пробуем по названию через `name_to_slug`
    (`match_title`). Индекс сервиса ключуется по снимкам, дубли одного предмета
    идут подряд — поэтому дедуп по slug.
    """
    # Просим с запасом: ниже мы схлопываем ракурсы одного предмета по slug и
    # выбрасываем названия, не сшитые с каталогом, — при limit=top_k до ответа
    # доезжал один вариант вместо трёх (см. recognition_search_limit).
    search_limit = max(top_k, settings.recognition_search_limit)
    try:
        async with httpx.AsyncClient(timeout=settings.recognition_timeout_sec) as client:
            resp = await client.post(
                settings.yolo_endpoint,  # type: ignore[arg-type]
                files={"file": ("photo.jpg", image, "application/octet-stream")},
                data={"limit": str(search_limit)},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Сервис распознавания недоступен: %r", exc)
        raise UpstreamError("Сервис распознавания временно недоступен.") from exc

    predictions = data.get("predictions") or []
    # Диагностика прода: без сырого ответа чинить сшивку вслепую невозможно.
    logger.info(
        "recognition: получено предсказаний=%d (limit=%d), found=%s, каталог=%d названий, сырые=%s",
        len(predictions), search_limit, data.get("found"), len(name_to_slug),
        [(p.get("item_id"), p.get("title_en") or p.get("title"), p.get("confidence")) for p in predictions],
    )

    known = set(known_slugs)
    slug_index = build_slug_index(known_slugs)
    name_index = build_name_index(name_to_slug)
    candidates: List[Tuple[str, float]] = []
    unmatched: List[Tuple[str, float]] = []
    seen: set[str] = set()
    for pred in predictions:
        title_en = str(pred.get("title_en") or "").strip()
        title = (pred.get("title") or "").strip()
        conf = pred.get("confidence")
        if conf is None:
            logger.warning("recognition: предсказание без confidence, отброшено: %r", pred)
            continue
        slug, how = match_slug(title_en, slug_index, known)
        if slug is None and title:
            slug, how = match_title(title, name_index)
            how = f"title/{how}"
        if slug is None:
            # Раньше здесь был тихий `continue` — именно поэтому баг «распознавание
            # не работает» не было видно по логам. Теперь идентификатор виден целиком.
            logger.warning(
                "recognition: предмет не сшит с каталогом, предсказание отброшено: "
                "title_en=%r title=%r item_id=%r confidence=%r",
                title_en, title, pred.get("item_id"), conf,
            )
            unmatched.append((title, float(conf)))
            continue
        if slug in seen:
            continue
        if how != "exact":
            logger.info(
                "recognition: предмет сшит способом %s: title_en=%r title=%r → %s",
                how, title_en, title, slug,
            )
        seen.add(slug)
        candidates.append((slug, float(conf)))
        if len(candidates) >= top_k:
            break

    if not candidates:
        # Уверенность верхнего предсказания отдаём даже без сшивки — она объясняет
        # фронту и логам, что модель что-то нашла, а споткнулся каталог.
        top_conf = unmatched[0][1] if unmatched else None
        return RecognitionOutcome(False, None, top_conf, [], unmatched)
    top_slug, top_conf = candidates[0]
    recognized = top_conf >= settings.recognition_confidence_threshold
    return RecognitionOutcome(
        recognized, top_slug if recognized else None, top_conf, candidates, unmatched
    )
