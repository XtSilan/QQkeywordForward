"""Audit log route."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import admin_guard
from app.db import connection
from app.repositories import audit_repo


router = APIRouter(prefix="/api", tags=["audit"], dependencies=[Depends(admin_guard)])


@router.get("/audit-logs")
def audit_logs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    with connection() as conn:
        return audit_repo.list_logs(conn, limit)