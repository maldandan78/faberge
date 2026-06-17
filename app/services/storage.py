"""Хранилище медиа (Yandex Object Storage + локальный стаб).

Прод: объекты пишутся в бакет Object Storage (`OBJECT_STORAGE_BUCKET`). Публичный
доступ настраивается на уровне бакета (bucket policy / read-public) — отдельный
ACL на объект не выставляется. Без бакета сервис пишет в локальный каталог
`MEDIA_DIR` (стаб для разработки и тестов).
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

from ..config import settings
from . import UpstreamError

logger = logging.getLogger(__name__)


@dataclass
class StoredObject:
    url: str
    object_key: str
    thumbnail_url: Optional[str] = None


# ── boto3-клиент: один на «тёплый» экземпляр функции ─────────────────────────
_s3_client = None


def _client():
    """Лениво создаёт и кэширует S3-клиент Object Storage (один на «тёплый» экземпляр).

    Регион не указываем: boto3 по умолчанию подписывает запросы как `us-east-1`,
    и Yandex Object Storage такую подпись принимает. Ключи берутся из переменных
    окружения (статический ключ сервисного аккаунта), как и в boto3 по умолчанию.
    """
    global _s3_client
    if _s3_client is None:
        import boto3  # импорт ленивый: нужен только в проде

        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
    return _s3_client


# ── Запись ───────────────────────────────────────────────────────────────────
async def save_image(data: bytes, filename: str, content_type: str, prefix: str = "exhibits") -> StoredObject:
    """Сохранить изображение и вернуть публичный URL + ключ объекта."""
    safe_name = os.path.basename(filename) or "image"
    object_key = f"{prefix}/{uuid.uuid4().hex}/{safe_name}"
    stored = await save_bytes(data, object_key, content_type)
    # Отдельной генерации миниатюр нет — отдаём тот же объект как thumbnail.
    stored.thumbnail_url = stored.url
    return stored


async def save_bytes(data: bytes, object_key: str, content_type: str) -> StoredObject:
    """Сохранить произвольные байты по заданному ключу (Object Storage или локальный стаб)."""
    if settings.storage_configured:
        return await asyncio.to_thread(_put_object_storage, data, object_key, content_type)
    return _save_local(data, object_key)


def _save_local(data: bytes, object_key: str) -> StoredObject:
    path = os.path.join(settings.media_dir, object_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return StoredObject(url=f"{settings.public_base_url}/media/{object_key}", object_key=object_key)


def _put_object_storage(data: bytes, object_key: str, content_type: str) -> StoredObject:
    try:
        _client().put_object(
            Bucket=settings.object_storage_bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
    except Exception as exc:  # noqa: BLE001
        raise UpstreamError("Хранилище объектов временно недоступно.") from exc
    return StoredObject(url=_public_url(object_key), object_key=object_key)


def _public_url(object_key: str) -> str:
    base = settings.object_storage_public_base or (
        f"{settings.object_storage_endpoint}/{settings.object_storage_bucket}"
    )
    return f"{base.rstrip('/')}/{object_key}"


# ── Удаление ─────────────────────────────────────────────────────────────────
async def delete_many(urls: List[str]) -> int:
    """Удалить объекты по их публичным URL. Best-effort: исключений не бросает.

    Возвращает число фактически удалённых объектов. Внешние URL (например,
    сид-данные на сторонних CDN) пропускаются — мы трогаем только то, что
    положили в собственный бакет / локальный каталог.
    """
    deleted = 0
    for url in dict.fromkeys(u for u in urls if u):  # дедуп, пропуск пустых
        try:
            if await delete_by_url(url):
                deleted += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось удалить объект %s: %s", url, exc)
    return deleted


async def delete_by_url(url: str) -> bool:
    """Удалить один объект, если URL принадлежит нашему хранилищу.

    True — если объект из нашего бакета/каталога (даже если его уже не было:
    delete у S3 идемпотентен). False — если URL внешний и трогать его не нужно.
    """
    key = _object_storage_key(url)
    if key is not None and settings.object_storage_bucket:
        await asyncio.to_thread(_delete_object_storage, key)
        return True
    local_key = _local_key(url)
    if local_key is not None:
        return _delete_local(local_key)
    return False


def _delete_object_storage(object_key: str) -> None:
    _client().delete_object(Bucket=settings.object_storage_bucket, Key=object_key)


def _delete_local(object_key: str) -> bool:
    path = os.path.join(settings.media_dir, object_key)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def _object_storage_key(url: str) -> Optional[str]:
    """Вернуть ключ объекта, если URL указывает на наш бакет Object Storage."""
    if not url:
        return None
    bases: List[str] = []
    if settings.object_storage_public_base:
        bases.append(settings.object_storage_public_base.rstrip("/") + "/")
    if settings.object_storage_bucket:
        endpoint = settings.object_storage_endpoint.rstrip("/")
        bucket = settings.object_storage_bucket
        bases.append(f"{endpoint}/{bucket}/")                       # path-style
        host = urlparse(endpoint).netloc
        if host:
            bases.append(f"https://{bucket}.{host}/")               # virtual-hosted-style
    for base in bases:
        if url.startswith(base):
            return url[len(base):]
    return None


def _local_key(url: str) -> Optional[str]:
    prefix = f"{settings.public_base_url.rstrip('/')}/media/"
    if url.startswith(prefix):
        return url[len(prefix):]
    return None
