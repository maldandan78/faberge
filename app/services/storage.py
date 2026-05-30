"""Хранилище медиа (Yandex Object Storage + локальный стаб)."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Optional

from ..config import settings
from . import UpstreamError


@dataclass
class StoredObject:
    url: str
    object_key: str
    thumbnail_url: Optional[str] = None


async def save_image(data: bytes, filename: str, content_type: str, prefix: str = "exhibits") -> StoredObject:
    """Сохранить изображение и вернуть публичный URL + ключ объекта."""
    safe_name = os.path.basename(filename) or "image"
    object_key = f"{prefix}/{uuid.uuid4().hex}/{safe_name}"
    if settings.storage_configured:
        return _save_object_storage(data, object_key, content_type)
    return _save_local(data, object_key)


def _save_local(data: bytes, object_key: str) -> StoredObject:
    path = os.path.join(settings.media_dir, object_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return StoredObject(url=f"{settings.public_base_url}/media/{object_key}", object_key=object_key)


def _save_object_storage(data: bytes, object_key: str, content_type: str) -> StoredObject:
    try:
        import boto3  # импорт ленивый: нужен только в проде

        s3 = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        s3.put_object(
            Bucket=settings.object_storage_bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
    except Exception as exc:  # noqa: BLE001
        raise UpstreamError("Хранилище объектов временно недоступно.") from exc

    base = settings.object_storage_public_base or (
        f"{settings.object_storage_endpoint}/{settings.object_storage_bucket}"
    )
    return StoredObject(url=f"{base}/{object_key}", object_key=object_key)
