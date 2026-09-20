"""Audit log route."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import admin_guard, row_dict
from app.db import connection


router = APIRouter(prefix="/api", tags=["audit"], dependencies=[Depends(admin_guard)])


@router.get("/audit-logs")
def audit_logs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, actor, action, resource_type, resource_id, detail_json, status_code, created_at "
            "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_dict(row) for row in rows]
