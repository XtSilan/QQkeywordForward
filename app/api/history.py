"""Keyword hit history route.

Filtering is server-side and paged: the client only ever receives one page of
rows. ``since``/``until`` arrive as UTC instants so the client owns the meaning
of "a day" (the browser knows its own timezone); omitting them lists all
history.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import admin_guard
from app.db import connection
from app.repositories import history_repo


router = APIRouter(prefix="/api", tags=["history"], dependencies=[Depends(admin_guard)])


def _bound(moment: datetime | None) -> str | None:
    """Normalise a bound to the way ``hit_at`` is stored."""
    return history_repo.storage_timestamp(moment) if moment else None


@router.get("/history")
def history(
    group_id: str | None = Query(default=None),
    keyword_id: int | None = Query(default=None),
    since: datetime | None = Query(default=None, description="含下界（UTC 瞬时）"),
    until: datetime | None = Query(default=None, description="不含上界（UTC 瞬时）"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with connection() as conn:
        return history_repo.list_hits(
            conn,
            group_id,
            keyword_id,
            _bound(since),
            _bound(until),
            limit,
            offset,
        )