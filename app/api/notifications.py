"""Notification routes: destinations, configs, per-group settings and email test."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.deps import admin_guard, row_dict
from app.db import bump_config_revision, connection
from app.schemas.notification import (
    DestinationCreate,
    DestinationUpdate,
    NotificationBulkApply,
    NotificationConfigCreate,
    NotificationSettingsPayload,
)
from app.settings import Settings, get_settings


router = APIRouter(prefix="/api", tags=["notifications"], dependencies=[Depends(admin_guard)])


@router.post("/notifications/test")
async def test_notification_email(
    payload: dict[str, str] = Body(...), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    from app.nonebot_bot import send_smtp_email

    address = str(payload.get("address", "")).strip()
    if "@" not in address:
        raise HTTPException(status_code=422, detail="invalid email address")
    try:
        await send_smtp_email(settings, address, "QQ Bot SMTP 测试", "这是一封来自 QQ Bot WebUI 的测试邮件。")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMTP 发送失败: {exc}") from exc
    return {"sent": True}


@router.get("/destinations")
def destinations() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT d.id, d.kind, d.address, d.display_name, d.enabled, d.created_at, "
            "COALESCE(GROUP_CONCAT(b.group_id), '') AS group_ids_csv "
            "FROM notification_destinations d LEFT JOIN notification_destination_bindings b "
            "ON b.destination_id=d.id GROUP BY d.id ORDER BY d.kind, d.id DESC"
        ).fetchall()
    result = []
    for row in rows:
        item = row_dict(row)
        item["group_ids"] = [value for value in item.pop("group_ids_csv", "").split(",") if value]
        result.append(item)
    return result


@router.post("/destinations")
def create_destination(payload: DestinationCreate) -> dict[str, Any]:
    address = payload.address.strip()
    if payload.kind == "email" and ("@" not in address or " " in address):
        raise HTTPException(status_code=422, detail="invalid email address")
    with connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO notification_destinations(kind, address, display_name) VALUES (?, ?, ?)",
                (payload.kind, address, payload.display_name.strip()),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="destination already exists") from exc
            raise
    return {"id": int(cursor.lastrowid), "revision": bump_config_revision()}


@router.post("/notification-configs")
def create_notification_config(payload: NotificationConfigCreate) -> dict[str, Any]:
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    if not group_ids:
        raise HTTPException(status_code=422, detail="at least one group is required")
    channels = list({(channel.kind, channel.address.strip()): channel for channel in payload.channels}.values())
    channel_kinds = {channel.kind for channel in channels}
    destination_ids: list[int] = []
    with connection() as conn:
        for channel in channels:
            address = channel.address.strip()
            if channel.kind == "qq" and not address.isdigit():
                raise HTTPException(status_code=422, detail="invalid QQ number")
            if channel.kind == "email" and ("@" not in address or " " in address):
                raise HTTPException(status_code=422, detail="invalid email address")
            existing = conn.execute(
                "SELECT id FROM notification_destinations WHERE kind=? AND address=?",
                (channel.kind, address),
            ).fetchone()
            if existing:
                destination_id = int(existing["id"])
                conn.execute(
                    "UPDATE notification_destinations SET display_name=?, enabled=1 WHERE id=?",
                    (channel.display_name.strip(), destination_id),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO notification_destinations(kind, address, display_name) VALUES (?, ?, ?)",
                    (channel.kind, address, channel.display_name.strip()),
                )
                destination_id = int(cursor.lastrowid)
            destination_ids.append(destination_id)
            for group_id in group_ids:
                conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
                conn.execute(
                    "INSERT OR IGNORE INTO notification_destination_bindings(group_id, destination_id) VALUES (?, ?)",
                    (group_id, destination_id),
                )
        # A newly-created reminder is immediately active for the selected
        # channel types.  The dispatcher requires both a destination binding
        # and the corresponding group-level switch to be enabled.
        for group_id in group_ids:
            conn.execute(
                "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id) DO UPDATE SET "
                "qq_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.qq_enabled END, "
                "email_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.email_enabled END, "
                "updated_at=CURRENT_TIMESTAMP",
                (
                    group_id,
                    int("qq" in channel_kinds),
                    int("email" in channel_kinds),
                    int("qq" in channel_kinds),
                    int("email" in channel_kinds),
                ),
            )
    return {"destination_ids": destination_ids, "group_ids": group_ids, "revision": bump_config_revision()}


@router.put("/destinations/{destination_id}")
def update_destination(destination_id: int, payload: DestinationUpdate) -> dict[str, Any]:
    address = payload.address.strip()
    if payload.kind == "email" and ("@" not in address or " " in address):
        raise HTTPException(status_code=422, detail="invalid email address")
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    if payload.kind == "qq" and not address.isdigit():
        raise HTTPException(status_code=422, detail="invalid QQ number")
    with connection() as conn:
        previous_groups = [
            str(row["group_id"])
            for row in conn.execute(
                "SELECT group_id FROM notification_destination_bindings WHERE destination_id=?",
                (destination_id,),
            ).fetchall()
        ]
        try:
            cursor = conn.execute(
                "UPDATE notification_destinations SET kind=?, address=?, display_name=?, enabled=? WHERE id=?",
                (payload.kind, address, payload.display_name.strip(), int(payload.enabled), destination_id),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="destination already exists") from exc
            raise
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="destination not found")
        conn.execute("DELETE FROM notification_destination_bindings WHERE destination_id=?", (destination_id,))
        for group_id in group_ids:
            conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
            conn.execute(
                "INSERT OR IGNORE INTO notification_destination_bindings(group_id, destination_id) VALUES (?, ?)",
                (group_id, destination_id),
            )
            conn.execute(
                "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id) DO UPDATE SET "
                "qq_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.qq_enabled END, "
                "email_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.email_enabled END, "
                "updated_at=CURRENT_TIMESTAMP",
                (
                    group_id,
                    int(payload.kind == "qq" and payload.enabled),
                    int(payload.kind == "email" and payload.enabled),
                    int(payload.kind == "qq" and payload.enabled),
                    int(payload.kind == "email" and payload.enabled),
                ),
            )
        # Recompute channel switches for both removed and newly-bound groups.
        # This avoids disabling a group-wide channel while another enabled
        # destination of the same type is still attached.
        for group_id in set(previous_groups) | set(group_ids):
            conn.execute(
                "INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,)
            )
            conn.execute(
                "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
                "VALUES (?, "
                "EXISTS(SELECT 1 FROM notification_destination_bindings b "
                "JOIN notification_destinations d ON d.id=b.destination_id "
                "WHERE b.group_id=? AND d.kind='qq' AND d.enabled=1), "
                "EXISTS(SELECT 1 FROM notification_destination_bindings b "
                "JOIN notification_destinations d ON d.id=b.destination_id "
                "WHERE b.group_id=? AND d.kind='email' AND d.enabled=1), CURRENT_TIMESTAMP) "
                "ON CONFLICT(group_id) DO UPDATE SET qq_enabled=excluded.qq_enabled, "
                "email_enabled=excluded.email_enabled, updated_at=CURRENT_TIMESTAMP",
                (group_id, group_id, group_id),
            )
    return {"updated": True, "revision": bump_config_revision()}


@router.delete("/destinations/{destination_id}")
def delete_destination(destination_id: int) -> dict[str, Any]:
    with connection() as conn:
        group_ids = [
            str(row["group_id"])
            for row in conn.execute(
                "SELECT group_id FROM notification_destination_bindings WHERE destination_id=?",
                (destination_id,),
            ).fetchall()
        ]
        # Remove dependent queue records explicitly because the existing
        # SQLite schema intentionally keeps foreign-key enforcement enabled.
        conn.execute("DELETE FROM notification_jobs WHERE destination_id=?", (destination_id,))
        conn.execute("DELETE FROM keyword_notification_bindings WHERE destination_id=?", (destination_id,))
        conn.execute("DELETE FROM notification_destination_bindings WHERE destination_id=?", (destination_id,))
        cursor = conn.execute("DELETE FROM notification_destinations WHERE id=?", (destination_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="destination not found")
        for group_id in group_ids:
            conn.execute(
                "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
                "VALUES (?, "
                "EXISTS(SELECT 1 FROM notification_destination_bindings b "
                "JOIN notification_destinations d ON d.id=b.destination_id "
                "WHERE b.group_id=? AND d.kind='qq' AND d.enabled=1), "
                "EXISTS(SELECT 1 FROM notification_destination_bindings b "
                "JOIN notification_destinations d ON d.id=b.destination_id "
                "WHERE b.group_id=? AND d.kind='email' AND d.enabled=1), CURRENT_TIMESTAMP) "
                "ON CONFLICT(group_id) DO UPDATE SET qq_enabled=excluded.qq_enabled, "
                "email_enabled=excluded.email_enabled, updated_at=CURRENT_TIMESTAMP",
                (group_id, group_id, group_id),
            )
    return {"deleted": True, "revision": bump_config_revision()}


@router.get("/groups/{group_id}/notification-settings")
def get_notification_settings(group_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            "SELECT qq_enabled, email_enabled FROM group_notification_settings WHERE group_id=?",
            (group_id,),
        ).fetchone()
        bindings = conn.execute(
            "SELECT destination_id FROM notification_destination_bindings WHERE group_id=?",
            (group_id,),
        ).fetchall()
    return {
        "group_id": group_id,
        "qq_enabled": bool(row["qq_enabled"]) if row else False,
        "email_enabled": bool(row["email_enabled"]) if row else False,
        "destination_ids": [int(item["destination_id"]) for item in bindings],
    }


@router.put("/groups/{group_id}/notification-settings")
def put_notification_settings(group_id: str, payload: NotificationSettingsPayload) -> dict[str, Any]:
    destination_ids = list(dict.fromkeys(payload.destination_ids))
    with connection() as conn:
        conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
        conn.execute(
            "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id) DO UPDATE SET "
            "qq_enabled=excluded.qq_enabled, email_enabled=excluded.email_enabled, updated_at=CURRENT_TIMESTAMP",
            (group_id, int(payload.qq_enabled), int(payload.email_enabled)),
        )
        conn.execute("DELETE FROM notification_destination_bindings WHERE group_id=?", (group_id,))
        for destination_id in destination_ids:
            conn.execute(
                "INSERT INTO notification_destination_bindings(group_id, destination_id) VALUES (?, ?)",
                (group_id, destination_id),
            )
    return {"saved": True, "revision": bump_config_revision()}


@router.post("/notification-settings/bulk-apply")
def bulk_apply_notification_settings(payload: NotificationBulkApply) -> dict[str, Any]:
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    if not group_ids:
        raise HTTPException(status_code=422, detail="at least one group is required")
    destination_ids = list(dict.fromkeys(payload.destination_ids))
    with connection() as conn:
        for group_id in group_ids:
            conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
            conn.execute(
                "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id) DO UPDATE SET "
                "qq_enabled=excluded.qq_enabled, email_enabled=excluded.email_enabled, updated_at=CURRENT_TIMESTAMP",
                (group_id, int(payload.qq_enabled), int(payload.email_enabled)),
            )
            conn.execute("DELETE FROM notification_destination_bindings WHERE group_id=?", (group_id,))
            for destination_id in destination_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO notification_destination_bindings(group_id, destination_id) VALUES (?, ?)",
                    (group_id, destination_id),
                )
    return {"applied": len(group_ids), "revision": bump_config_revision()}
