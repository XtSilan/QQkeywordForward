"""Keyword routes: CRUD, bulk operations, ordering and notification bindings."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import admin_guard, row_dict
from app.db import bump_config_revision, connection
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


@router.get("/keywords")
def keywords(group_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT r.id, r.display_text, r.match_mode, r.ignore_case, r.created_at, "
            "r.updated_at, r.sort_order, COUNT(DISTINCT b.group_id) AS group_count "
            "FROM keyword_rules r LEFT JOIN group_keyword_bindings b "
            "ON b.keyword_id = r.id AND b.enabled = 1 "
            "WHERE r.deleted_at IS NULL "
            "AND (? IS NULL OR EXISTS (SELECT 1 FROM group_keyword_bindings gb "
            "WHERE gb.keyword_id = r.id AND gb.group_id = ?)) "
            "GROUP BY r.id ORDER BY r.sort_order ASC, r.display_text COLLATE NOCASE ASC, r.id DESC",
            (group_id, group_id),
        ).fetchall()
        result = [row_dict(row) for row in rows]
        for item in result:
            bindings = conn.execute(
                "SELECT group_id, enabled, cooldown_seconds FROM group_keyword_bindings "
                "WHERE keyword_id = ? ORDER BY group_id",
                (item["id"],),
            ).fetchall()
            item["bindings"] = [row_dict(binding) for binding in bindings]
            destinations = conn.execute(
                "SELECT destination_id FROM keyword_notification_bindings "
                "WHERE keyword_id=? AND enabled=1 ORDER BY destination_id",
                (item["id"],),
            ).fetchall()
            item["destination_ids"] = [int(destination["destination_id"]) for destination in destinations]
    return result


@router.post("/keywords")
def create_keyword(payload: KeywordCreate) -> dict[str, Any]:
    display_text = payload.display_text.strip()
    if not display_text:
        raise HTTPException(status_code=422, detail="display_text cannot be blank")
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    try:
        with connection() as conn:
            next_order_row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM keyword_rules WHERE deleted_at IS NULL"
            ).fetchone()
            next_order = int(next_order_row[0]) if next_order_row else 1
            cursor = conn.execute(
                "INSERT INTO keyword_rules(display_text, pattern, match_mode, ignore_case, sort_order, updated_at) "
                "VALUES (?, ?, 'literal_search', 1, ?, CURRENT_TIMESTAMP)",
                (display_text, re.escape(display_text), next_order),
            )
            keyword_id = int(cursor.lastrowid)
            for group_id in group_ids:
                conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
                conn.execute(
                    "INSERT INTO group_keyword_bindings(group_id, keyword_id, enabled, cooldown_seconds) "
                    "VALUES (?, ?, ?, ?)",
                    (group_id, keyword_id, int(payload.enabled), payload.cooldown_seconds),
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
        if destination_ids:
            placeholders = ",".join("?" for _ in destination_ids)
            rows = conn.execute(
                f"SELECT id, kind FROM notification_destinations WHERE id IN ({placeholders}) AND enabled=1",
                destination_ids,
            ).fetchall()
            if len(rows) != len(destination_ids):
                raise HTTPException(status_code=422, detail="提醒目标不存在或已关闭")
            destination_kinds = {str(row["kind"]) for row in rows}
        else:
            destination_kinds = set()
        keyword_ids: list[int] = []
        try:
            for display_text in keywords:
                existing = conn.execute(
                    "SELECT id FROM keyword_rules WHERE display_text=? AND deleted_at IS NULL",
                    (display_text,),
                ).fetchone()
                if existing:
                    keyword_id = int(existing["id"])
                    conn.execute(
                        "UPDATE keyword_rules SET pattern=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (re.escape(display_text), keyword_id),
                    )
                else:
                    next_order_row = conn.execute(
                        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM keyword_rules WHERE deleted_at IS NULL"
                    ).fetchone()
                    next_order = int(next_order_row[0]) if next_order_row else 1
                    cursor = conn.execute(
                        "INSERT INTO keyword_rules(display_text, pattern, match_mode, ignore_case, sort_order, updated_at) "
                        "VALUES (?, ?, 'literal_search', 1, ?, CURRENT_TIMESTAMP)",
                        (display_text, re.escape(display_text), next_order),
                    )
                    keyword_id = int(cursor.lastrowid)
                keyword_ids.append(keyword_id)
                for group_id in group_ids:
                    conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
                    conn.execute(
                        "INSERT INTO group_keyword_bindings(group_id, keyword_id, enabled, cooldown_seconds) "
                        "VALUES (?, ?, ?, ?) ON CONFLICT(group_id, keyword_id) DO UPDATE SET "
                        "enabled=excluded.enabled, cooldown_seconds=excluded.cooldown_seconds, updated_at=CURRENT_TIMESTAMP",
                        (group_id, keyword_id, int(payload.enabled), payload.cooldown_seconds),
                    )
                conn.execute("DELETE FROM keyword_notification_bindings WHERE keyword_id=?", (keyword_id,))
                for destination_id in destination_ids:
                    conn.execute(
                        "INSERT INTO keyword_notification_bindings(keyword_id, destination_id, enabled) VALUES (?, ?, 1)",
                        (keyword_id, destination_id),
                    )
            for group_id in group_ids:
                conn.execute(
                    "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id) DO UPDATE SET "
                    "qq_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.qq_enabled END, "
                    "email_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.email_enabled END, "
                    "updated_at=CURRENT_TIMESTAMP",
                    (
                        group_id,
                        int("qq" in destination_kinds),
                        int("email" in destination_kinds),
                        int("qq" in destination_kinds),
                        int("email" in destination_kinds),
                    ),
                )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="keyword already exists") from exc
            raise
    return {"keyword_ids": keyword_ids, "group_ids": group_ids, "destination_ids": destination_ids, "revision": bump_config_revision()}


@router.patch("/keywords/{keyword_id}")
def update_keyword(keyword_id: int, payload: KeywordUpdate) -> dict[str, Any]:
    changes: list[str] = []
    values: list[Any] = []
    if payload.display_text is not None:
        display_text = payload.display_text.strip()
        if not display_text:
            raise HTTPException(status_code=422, detail="display_text cannot be blank")
        changes.extend(["display_text = ?", "pattern = ?"])
        values.extend([display_text, re.escape(display_text)])
    if payload.enabled is not None:
        changes.append("enabled = ?")
        values.append(int(payload.enabled))
    if payload.cooldown_seconds is not None:
        changes.append("cooldown_seconds = ?")
        values.append(payload.cooldown_seconds)
    if not changes:
        raise HTTPException(status_code=400, detail="no changes supplied")
    with connection() as conn:
        exists = conn.execute(
            "SELECT id FROM keyword_rules WHERE id = ? AND deleted_at IS NULL", (keyword_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="keyword not found")
        if payload.display_text is not None:
            try:
                conn.execute(
                    "UPDATE keyword_rules SET display_text=?, pattern=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (values[0], values[1], keyword_id),
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise HTTPException(status_code=409, detail="keyword already exists") from exc
            changes = [change for change in changes if not change.startswith("display_text") and not change.startswith("pattern")]
            values = values[2:]
        if changes:
            conn.execute(
                f"UPDATE group_keyword_bindings SET {', '.join(changes)}, updated_at=CURRENT_TIMESTAMP "
                "WHERE keyword_id = ?",
                (*values, keyword_id),
            )
        conn.execute("UPDATE keyword_rules SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (keyword_id,))
    return {"updated": True, "revision": bump_config_revision()}


@router.post("/keywords/bulk-toggle")
def bulk_toggle_keywords(payload: KeywordBulkUpdate) -> dict[str, Any]:
    with connection() as conn:
        placeholders = ",".join("?" for _ in payload.keyword_ids)
        cursor = conn.execute(
            f"UPDATE group_keyword_bindings SET enabled=?, updated_at=CURRENT_TIMESTAMP "
            f"WHERE keyword_id IN ({placeholders})",
            (int(payload.enabled), *payload.keyword_ids),
        )
        if cursor.rowcount == 0:
            # No bindings to update — still flip the keyword_rules default so
            # future bindings inherit the desired state.
            conn.execute(
                f"UPDATE keyword_rules SET enabled=?, updated_at=CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders})",
                (int(payload.enabled), *payload.keyword_ids),
            )
        conn.execute(
            f"UPDATE keyword_rules SET updated_at=CURRENT_TIMESTAMP "
            f"WHERE id IN ({placeholders})",
            tuple(payload.keyword_ids),
        )
    return {"updated": len(payload.keyword_ids), "enabled": payload.enabled, "revision": bump_config_revision()}


@router.post("/keywords/bulk-delete")
def bulk_delete_keywords(payload: KeywordBulkUpdate) -> dict[str, Any]:
    with connection() as conn:
        placeholders = ",".join("?" for _ in payload.keyword_ids)
        conn.execute(
            f"UPDATE keyword_rules SET deleted_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            tuple(payload.keyword_ids),
        )
    return {"deleted": len(payload.keyword_ids), "revision": bump_config_revision()}


@router.post("/keywords/reorder")
def reorder_keywords(payload: KeywordReorder) -> dict[str, Any]:
    if not payload.alphabetical and not payload.keyword_ids:
        raise HTTPException(status_code=422, detail="keyword_ids is required for manual reorder")
    with connection() as conn:
        if payload.alphabetical:
            conn.execute(
                "UPDATE keyword_rules SET sort_order = (SELECT COUNT(*) FROM keyword_rules AS k "
                "WHERE k.deleted_at IS NULL AND (k.display_text COLLATE NOCASE "
                "< keyword_rules.display_text COLLATE NOCASE "
                "OR (k.display_text = keyword_rules.display_text AND k.id < keyword_rules.id)) ) + 1 "
                "WHERE deleted_at IS NULL"
            )
        else:
            for index, keyword_id in enumerate(payload.keyword_ids, start=1):
                conn.execute(
                    "UPDATE keyword_rules SET sort_order=? WHERE id=?", (index, keyword_id)
                )
    return {"reordered": len(payload.keyword_ids), "alphabetical": payload.alphabetical, "revision": bump_config_revision()}


@router.put("/keywords/{keyword_id}/notifications")
def update_keyword_notifications(keyword_id: int, payload: KeywordNotificationUpdate) -> dict[str, Any]:
    destination_ids = list(dict.fromkeys(int(destination_id) for destination_id in payload.destination_ids))
    with connection() as conn:
        exists = conn.execute(
            "SELECT id FROM keyword_rules WHERE id=? AND deleted_at IS NULL", (keyword_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="keyword not found")
        destination_kinds: set[str] = set()
        if destination_ids:
            placeholders = ",".join("?" for _ in destination_ids)
            rows = conn.execute(
                f"SELECT id, kind FROM notification_destinations WHERE id IN ({placeholders}) AND enabled=1",
                destination_ids,
            ).fetchall()
            if len(rows) != len(destination_ids):
                raise HTTPException(status_code=422, detail="提醒目标不存在或已关闭")
            destination_kinds = {str(row["kind"]) for row in rows}
        groups = [
            str(row["group_id"])
            for row in conn.execute(
                "SELECT group_id FROM group_keyword_bindings WHERE keyword_id=?", (keyword_id,)
            ).fetchall()
        ]
        conn.execute("DELETE FROM keyword_notification_bindings WHERE keyword_id=?", (keyword_id,))
        for destination_id in destination_ids:
            conn.execute(
                "INSERT INTO keyword_notification_bindings(keyword_id, destination_id, enabled) VALUES (?, ?, 1)",
                (keyword_id, destination_id),
            )
        for group_id in groups:
            conn.execute(
                "INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,)
            )
            conn.execute(
                "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id) DO UPDATE SET "
                "qq_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.qq_enabled END, "
                "email_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.email_enabled END, "
                "updated_at=CURRENT_TIMESTAMP",
                (
                    group_id,
                    int("qq" in destination_kinds),
                    int("email" in destination_kinds),
                    int("qq" in destination_kinds),
                    int("email" in destination_kinds),
                ),
            )
    return {"updated": True, "destination_ids": destination_ids, "revision": bump_config_revision()}


@router.delete("/keywords/{keyword_id}")
def delete_keyword(keyword_id: int) -> dict[str, Any]:
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE keyword_rules SET deleted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND deleted_at IS NULL",
            (keyword_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="keyword not found")
    return {"deleted": True, "revision": bump_config_revision()}


@router.post("/keywords/bulk-apply")
def bulk_apply_keyword(payload: KeywordBulkApply) -> dict[str, Any]:
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    with connection() as conn:
        keyword = conn.execute(
            "SELECT id FROM keyword_rules WHERE id=? AND deleted_at IS NULL", (payload.keyword_id,)
        ).fetchone()
        if not keyword:
            raise HTTPException(status_code=404, detail="keyword not found")
        if payload.replace_existing:
            if group_ids:
                placeholders = ",".join("?" for _ in group_ids)
                conn.execute(
                    f"DELETE FROM group_keyword_bindings WHERE keyword_id=? AND group_id NOT IN ({placeholders})",
                    (payload.keyword_id, *group_ids),
                )
            else:
                conn.execute("DELETE FROM group_keyword_bindings WHERE keyword_id=?", (payload.keyword_id,))
        for group_id in group_ids:
            conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
            conn.execute(
                "INSERT INTO group_keyword_bindings(group_id, keyword_id, enabled, cooldown_seconds) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(group_id, keyword_id) DO UPDATE SET "
                "enabled=excluded.enabled, cooldown_seconds=excluded.cooldown_seconds, "
                "updated_at=CURRENT_TIMESTAMP",
                (group_id, payload.keyword_id, int(payload.enabled), payload.cooldown_seconds),
            )
    return {"applied": len(group_ids), "revision": bump_config_revision()}
