"""Администрирование [вне MVP]: CRUD экспонатов, медиа, аналитика."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from .. import schemas as sch
from ..config import settings
from ..db import get_session
from ..dependencies import require_admin
from ..services import UpstreamError, storage

router = APIRouter(prefix="/admin", tags=["Администрирование"], dependencies=[Depends(require_admin)])

_ALLOWED_IMG = {"image/jpeg", "image/png", "image/webp"}


@router.post("/halls", response_model=sch.HallDetail, status_code=201, summary="[Вне MVP] Создать зал")
async def create_hall(data: sch.HallCreate, session: AsyncSession = Depends(get_session)) -> sch.HallDetail:
    try:
        return await crud.create_hall(session, data)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Зал с таким номером уже существует.")


@router.post("/showcases", response_model=sch.ShowcaseDetail, status_code=201, summary="[Вне MVP] Создать витрину")
async def create_showcase(data: sch.ShowcaseCreate, session: AsyncSession = Depends(get_session)) -> sch.ShowcaseDetail:
    if not await crud.hall_exists(session, data.hall_id):
        raise HTTPException(status_code=404, detail="Зал не найден.")
    try:
        return await crud.create_showcase(session, data)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Витрина с таким номером уже существует в этом зале.")


@router.post("/exhibits", response_model=sch.ExhibitAdmin, status_code=201, summary="[Вне MVP] Создать экспонат")
async def create_exhibit(data: sch.ExhibitCreate, session: AsyncSession = Depends(get_session)) -> sch.ExhibitAdmin:
    if not await crud.showcase_exists(session, data.showcase_id):
        raise HTTPException(status_code=404, detail="Витрина не найдена.")
    try:
        ex = await crud.create_exhibit(session, data)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Экспонат с таким label_slug уже существует.")
    return crud.to_exhibit(ex, admin=True)


@router.put("/exhibits/{exhibit_id}", response_model=sch.ExhibitAdmin, summary="[Вне MVP] Полностью обновить экспонат")
async def update_exhibit(
    data: sch.ExhibitUpdate, exhibit_id: int = Path(ge=1), session: AsyncSession = Depends(get_session)
) -> sch.ExhibitAdmin:
    ex = await crud.get_exhibit_orm(session, exhibit_id)
    if ex is None:
        raise HTTPException(status_code=404, detail="Экспонат не найден.")
    try:
        ex = await crud.replace_exhibit(session, ex, data)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Нарушение уникальности label_slug.")
    return crud.to_exhibit(ex, admin=True)


@router.patch("/exhibits/{exhibit_id}", response_model=sch.ExhibitAdmin, summary="[Вне MVP] Частично обновить экспонат")
async def patch_exhibit(
    data: sch.ExhibitPatch, exhibit_id: int = Path(ge=1), session: AsyncSession = Depends(get_session)
) -> sch.ExhibitAdmin:
    ex = await crud.get_exhibit_orm(session, exhibit_id)
    if ex is None:
        raise HTTPException(status_code=404, detail="Экспонат не найден.")
    try:
        ex = await crud.patch_exhibit(session, ex, data)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Нарушение уникальности label_slug.")
    return crud.to_exhibit(ex, admin=True)


@router.delete("/exhibits/{exhibit_id}", status_code=204, summary="[Вне MVP] Удалить экспонат")
async def delete_exhibit(exhibit_id: int = Path(ge=1), session: AsyncSession = Depends(get_session)) -> None:
    ex = await crud.get_exhibit_orm(session, exhibit_id)
    if ex is None:
        raise HTTPException(status_code=404, detail="Экспонат не найден.")
    await crud.delete_exhibit(session, ex)


@router.post(
    "/exhibits/{exhibit_id}/media", response_model=sch.MediaUploadResponse, status_code=201,
    summary="[Вне MVP] Загрузить фото экспоната",
)
async def upload_media(
    exhibit_id: int = Path(ge=1),
    file: UploadFile = File(...),
    is_primary: bool = Form(False),
    session: AsyncSession = Depends(get_session),
) -> sch.MediaUploadResponse:
    if not await _exhibit_exists(session, exhibit_id):
        raise HTTPException(status_code=404, detail="Экспонат не найден.")
    if file.content_type not in _ALLOWED_IMG:
        raise HTTPException(status_code=415, detail="Поддерживаются только JPEG, PNG и WebP.")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Размер файла превышает {settings.max_upload_mb} МБ.")
    try:
        stored = await storage.save_image(data, file.filename or "image", file.content_type)
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=exc.message)
    await crud.add_exhibit_image(session, exhibit_id, stored.url, is_primary)
    return sch.MediaUploadResponse(image_url=stored.url, thumbnail_url=stored.thumbnail_url, object_key=stored.object_key)


@router.get("/analytics/overview", response_model=sch.AnalyticsOverview, summary="[Вне MVP] Сводная аналитика")
async def analytics_overview(
    from_: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> sch.AnalyticsOverview:
    return await crud.analytics_overview(session, from_, to)


async def _exhibit_exists(session: AsyncSession, exhibit_id: int) -> bool:
    return (await crud.get_exhibit_orm(session, exhibit_id)) is not None
