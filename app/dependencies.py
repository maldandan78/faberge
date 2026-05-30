"""Общие зависимости FastAPI: пагинация и авторизация администратора."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings


@dataclass
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: int = Query(20, ge=1, le=100, description="Максимум элементов на странице."),
    offset: int = Query(0, ge=0, description="Смещение от начала выборки."),
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


_bearer = HTTPBearer(auto_error=False, description="Bearer-токен администратора.")


def require_admin(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> None:
    if creds is None or creds.credentials != settings.admin_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
