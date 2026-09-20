"""Keyword routes: CRUD, bulk operations, ordering and notification bindings.

HTTP/validation concerns only — data access delegates to
``app.repositories.keyword_repo`` / ``group_repo``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import admin_guard
from app.db import bump_config_revision, connection
from app.repositories import group_repo, keyword_repo
from app.schemas.keyword import (
    KeywordBulkApply,
    KeywordBulkUpdate,
    KeywordConfigCreate,
    KeywordCreate,
    KeywordNotificationUpdate,
    KeywordReorder,
    KeywordUpdate,
)


router = APIRouter(prefix="/api", tags=["keywords"], dependencies=[Depends(admin_guard)])


def _destination_kinds(conn, destination_ids: list[int]) -> set[str]:
    if not destination_ids:
        return set()
    placeholders = ",".join("?" for _ in destination_ids)
    rows = conn.execute(
        f"SELECT id, kind FROM notification_destinations WHERE id IN ({placeholders}) AND enabled=1",
        destination_ids,
    ).fetchall()
    if len(rows) != len(destination_ids):
        raise HTTPException(status_code=422, detail="提醒目标不存在或已关闭")
    return {str(row["kind"]) for row in rows}


@router.get("/keywords")
def keywords(group_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
    with connection() as conn:
        return keyword_repo.list_keywords(conn, group_id)


@router.post("/keywords")
def create_keyword(payload: KeywordCreate) -> dict[str, Any]:
    display_text = payload.display_text.strip()
    if not display_text:
        raise HTTPException(status_code=422, detail="display_text cannot be blank")
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    try:
        with connection() as conn:
            keyword_id = keyword_repo.create(
                conn, display_text, group_ids, payload.enabled, payload.cooldown_seconds
            )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="keyword already exists") from exc
        raise
    revision = bump_config_revision()
    return {"id": keyword_id, "display_text": display_text, "group_ids": group_ids, "revision": revision}


@router.post("/keyword-configs")
def create_keyword_config(payload: KeywordConfigCreate) -> dict[str, Any]:
    keywords = list(dict.fromkeys(keyword.strip() for keyword in payload.keywords if keyword.strip()))
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    destination_ids = list(dict.fromkeys(int(destination_id) for destination_id in payload.destination_ids))
    if not keywords:
        raise HTTPException(status_code=422, detail="at least one keyword is required")
    if not group_ids:
        raise HTTPException(status_code=422, detail="at least one group is required")
    with connection() as conn:
        destination_kinds = _destination_kinds(conn, destination_ids)
        keyword_ids: list[int] = []
        try:
            for display_text in keywords:
                existing = keyword_repo.find_by_text(conn, display_text)
                if existing:
                    keyword_id = existing
                    keyword_repo.upsert_pattern(conn, display_text, keyword_id)
                else:
                    keyword_id = keyword_repo.insert(conn, display_text, keyword_repo.next_sort_order(conn))
                keyword_ids.append(keyword_id)
                keyword_repo.bind_groups(conn, keyword_id, group_ids, payload.enabled, payload.cooldown_seconds)
                keyword_repo.set_notifications(conn, keyword_id, destination_ids)
            for group_id in group_ids:
                group_repo.enable_channels(
                    conn, group_id, "qq" in destination_kinds, "email" in destination_kinds
                )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="keyword already exists") from exc
            raise
    return {"keyword_ids": keyword_ids, "group_ids": group_ids, "destination_ids": destination_ids, "revision": bump_config_revision()}


@router.patch("/keywords/{keyword_id}")
def update_keyword(keyword_id: int, payload: KeywordUpdate) -> dict[str, Any]:
    display_text = None
    if payload.display_text is not None:
        display_text = payload.display_text.strip()
        if not display_text:
            raise HTTPException(status_code=422, detail="display_text cannot be blank")
    have_changes = (
        display_text is not None
        or payload.enabled is not None
        or payload.cooldown_seconds is not None
    )
    if not have_changes:
        raise HTTPException(status_code=400, detail="no changes supplied")
    with connection() as conn:
        if not keyword_repo.get_by_id(conn, keyword_id):
            raise HTTPException(status_code=404, detail="keyword not found")
        if display_text is not None:
            try:
                keyword_repo.update_display(conn, keyword_id, display_text)
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise HTTPException(status_code=409, detail="keyword already exists") from exc
        if payload.enabled is not None or payload.cooldown_seconds is not None:
            keyword_repo.update_bindings(conn, keyword_id, payload.enabled, payload.cooldown_seconds)
    return {"updated": True, "revision": bump_config_revision()}


@router.post("/keywords/bulk-toggle")
def bulk_toggle_keywords(payload: KeywordBulkUpdate) -> dict[str, Any]:
    with connection() as conn:
        keyword_repo.bulk_toggle(conn, payload.keyword_ids, payload.enabled)
    return {"updated": len(payload.keyword_ids), "enabled": payload.enabled, "revision": bump_config_revision()}


@router.post("/keywords/bulk-delete")
def bulk_delete_keywords(payload: KeywordBulkUpdate) -> dict[str, Any]:
    with connection() as conn:
        keyword_repo.bulk_delete(conn, payload.keyword_ids)
    return {"deleted": len(payload.keyword_ids), "revision": bump_config_revision()}


@router.post("/keywords/reorder")
def reorder_keywords(payload: KeywordReorder) -> dict[str, Any]:
    if not payload.alphabetical and not payload.keyword_ids:
        raise HTTPException(status_code=422, detail="keyword_ids is required for manual reorder")
    with connection() as conn:
        if payload.alphabetical:
            keyword_repo.reorder_alphabetical(conn)
        else:
            keyword_repo.reorder_manual(conn, payload.keyword_ids)
    return {"reordered": len(payload.keyword_ids), "alphabetical": payload.alphabetical, "revision": bump_config_revision()}


@router.put("/keywords/{keyword_id}/notifications")
def update_keyword_notifications(keyword_id: int, payload: KeywordNotificationUpdate) -> dict[str, Any]:
    destination_ids = list(dict.fromkeys(int(destination_id) for destination_id in payload.destination_ids))
    with connection() as conn:
        if not keyword_repo.get_by_id(conn, keyword_id):
            raise HTTPException(status_code=404, detail="keyword not found")
        destination_kinds = _destination_kinds(conn, destination_ids)
        groups = keyword_repo.binding_groups(conn, keyword_id)
        keyword_repo.set_notifications(conn, keyword_id, destination_ids)
        for group_id in groups:
            group_repo.enable_channels(
                conn, group_id, "qq" in destination_kinds, "email" in destination_kinds
            )
    return {"updated": True, "destination_ids": destination_ids, "revision": bump_config_revision()}


@router.delete("/keywords/{keyword_id}")
def delete_keyword(keyword_id: int) -> dict[str, Any]:
    with connection() as conn:
        if not keyword_repo.soft_delete(conn, keyword_id):
            raise HTTPException(status_code=404, detail="keyword not found")
    return {"deleted": True, "revision": bump_config_revision()}


@router.post("/keywords/bulk-apply")
def bulk_apply_keyword(payload: KeywordBulkApply) -> dict[str, Any]:
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    with connection() as conn:
        if not keyword_repo.get_by_id(conn, payload.keyword_id):
            raise HTTPException(status_code=404, detail="keyword not found")
        applied = keyword_repo.bulk_apply_groups(
            conn, payload.keyword_id, group_ids, payload.enabled,
            payload.cooldown_seconds, payload.replace_existing,
        )
    return {"applied": applied, "revision": bump_config_revision()}