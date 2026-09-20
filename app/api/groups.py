"""Group routes: listing and sync."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import admin_guard, row_dict
from app.db import connection
from app.schemas.group import GroupPayload


router = APIRouter(prefix="/api/groups", tags=["groups"], dependencies=[Depends(admin_guard)])


@router.get("")
def groups() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT group_id, name, avatar_url, enabled, last_synced_at "
            "FROM groups ORDER BY name COLLATE NOCASE, group_id"
        ).fetchall()
    return [row_dict(row) for row in rows]


@router.post("/sync")
def sync_groups(payload: list[GroupPayload]) -> dict[str, int]:
    with connection() as conn:
        for group in payload:
            conn.execute(
                "INSERT INTO groups(group_id, name, avatar_url, last_synced_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(group_id) DO UPDATE SET name=excluded.name, "
                "avatar_url=excluded.avatar_url, last_synced_at=CURRENT_TIMESTAMP",
                (group.group_id, group.name, group.avatar_url),
            )
    return {"synced": len(payload)}
