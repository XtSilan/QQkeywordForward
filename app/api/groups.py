"""Group routes: listing and sync."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import admin_guard
from app.db import connection
from app.repositories import group_repo
from app.schemas.group import GroupPayload


router = APIRouter(prefix="/api/groups", tags=["groups"], dependencies=[Depends(admin_guard)])


@router.get("")
def groups() -> list[dict[str, Any]]:
    with connection() as conn:
        return group_repo.list_groups(conn)


@router.post("/sync")
def sync_groups(payload: list[GroupPayload]) -> dict[str, int]:
    with connection() as conn:
        for group in payload:
            group_repo.upsert_group(conn, group.group_id, group.name, group.avatar_url)
    return {"synced": len(payload)}