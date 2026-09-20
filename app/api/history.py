"""Keyword hit history route."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import admin_guard, row_dict
from app.db import connection


router = APIRouter(prefix="/api", tags=["history"], dependencies=[Depends(admin_guard)])


@router.get("/history")
def history(
    group_id: str | None = Query(default=None),
    keyword_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, group_id, group_name, sender_id, sender_name, keyword_id, "
            "keyword_text_snapshot, message_text, message_id, hit_at, notify_status "
            "FROM keyword_hits WHERE (? IS NULL OR group_id=?) "
            "AND (? IS NULL OR keyword_id=?) ORDER BY hit_at DESC LIMIT ? OFFSET ?",
            (group_id, group_id, keyword_id, keyword_id, limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM keyword_hits WHERE (? IS NULL OR group_id=?) "
            "AND (? IS NULL OR keyword_id=?)",
            (group_id, group_id, keyword_id, keyword_id),
        ).fetchone()["count"]
    return {"items": [row_dict(row) for row in rows], "total": int(total), "limit": limit, "offset": offset}
