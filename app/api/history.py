"""Keyword hit history route."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import admin_guard
from app.db import connection
from app.repositories import history_repo


router = APIRouter(prefix="/api", tags=["history"], dependencies=[Depends(admin_guard)])


@router.get("/history")
def history(
    group_id: str | None = Query(default=None),
    keyword_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with connection() as conn:
        return history_repo.list_hits(conn, group_id, keyword_id, limit, offset)