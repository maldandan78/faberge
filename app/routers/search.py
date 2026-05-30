"""Поиск по залам и экспонатам."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from .. import schemas as sch
from ..db import get_session

router = APIRouter(tags=["Поиск"])


@router.get("/search", response_model=sch.SearchResponse, summary="Поиск по залам и экспонатам")
async def search(
    q: str = Query(..., min_length=1, description="Название зала или экспоната."),
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> sch.SearchResponse:
    return await crud.search(session, q, limit)
