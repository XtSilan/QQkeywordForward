"""Notification routes: destinations, configs, per-group settings and email test.

HTTP/validation concerns only — data access delegates to
``app.repositories.notification_repo`` / ``group_repo``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.deps import admin_guard
from app.db import bump_config_revision, connection
from app.repositories import group_repo, notification_repo
from app.schemas.notification import (
    DestinationCreate,
    DestinationUpdate,
    NotificationBulkApply,
    NotificationConfigCreate,
    NotificationSettingsPayload,
)
from app.services.email import send_smtp_email
from app.settings import Settings, get_settings


router = APIRouter(prefix="/api", tags=["notifications"], dependencies=[Depends(admin_guard)])


@router.post("/notifications/test")
async def test_notification_email(
    payload: dict[str, str] = Body(...), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
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
        return notification_repo.list_destinations(conn)


@router.post("/destinations")
def create_destination(payload: DestinationCreate) -> dict[str, Any]:
    address = payload.address.strip()
    if payload.kind == "email" and ("@" not in address or " " in address):
        raise HTTPException(status_code=422, detail="invalid email address")
    with connection() as conn:
        try:
            destination_id = notification_repo.insert(conn, payload.kind, address, payload.display_name.strip())
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="destination already exists") from exc
            raise
    return {"id": destination_id, "revision": bump_config_revision()}


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
            existing = notification_repo.find_by_address(conn, channel.kind, address)
            if existing:
                destination_id = existing
                notification_repo.enable(conn, destination_id, channel.display_name.strip())
            else:
                destination_id = notification_repo.insert(conn, channel.kind, address, channel.display_name.strip())
            destination_ids.append(destination_id)
            for group_id in group_ids:
                group_repo.ensure_group(conn, group_id)
                notification_repo.bind_group(conn, group_id, destination_id)
        # A newly-created reminder is immediately active for the selected
        # channel types. The dispatcher requires both a destination binding and
        # the corresponding group-level switch to be enabled.
        for group_id in group_ids:
            group_repo.enable_channels(
                conn, group_id, "qq" in channel_kinds, "email" in channel_kinds
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
        previous_groups = notification_repo.destination_groups(conn, destination_id)
        try:
            found = notification_repo.update(
                conn, destination_id, payload.kind, address, payload.display_name.strip(), payload.enabled
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="destination already exists") from exc
            raise
        if not found:
            raise HTTPException(status_code=404, detail="destination not found")
        notification_repo.clear_destination(conn, destination_id)
        for group_id in group_ids:
            group_repo.ensure_group(conn, group_id)
            notification_repo.bind_group(conn, group_id, destination_id)
            group_repo.enable_channels(
                conn, group_id,
                payload.kind == "qq" and payload.enabled,
                payload.kind == "email" and payload.enabled,
            )
        # Recompute channel switches for both removed and newly-bound groups.
        # This avoids disabling a group-wide channel while another enabled
        # destination of the same type is still attached.
        for group_id in set(previous_groups) | set(group_ids):
            group_repo.recompute_channels(conn, group_id)
    return {"updated": True, "revision": bump_config_revision()}


@router.delete("/destinations/{destination_id}")
def delete_destination(destination_id: int) -> dict[str, Any]:
    with connection() as conn:
        group_ids = notification_repo.destination_groups(conn, destination_id)
        notification_repo.purge_references(conn, destination_id)
        if not notification_repo.delete(conn, destination_id):
            raise HTTPException(status_code=404, detail="destination not found")
        for group_id in group_ids:
            group_repo.recompute_channels(conn, group_id)
    return {"deleted": True, "revision": bump_config_revision()}


@router.get("/groups/{group_id}/notification-settings")
def get_notification_settings(group_id: str) -> dict[str, Any]:
    with connection() as conn:
        qq_enabled, email_enabled = group_repo.get_channels(conn, group_id)
        destination_ids = notification_repo.group_destination_ids(conn, group_id)
    return {
        "group_id": group_id,
        "qq_enabled": qq_enabled,
        "email_enabled": email_enabled,
        "destination_ids": destination_ids,
    }


@router.put("/groups/{group_id}/notification-settings")
def put_notification_settings(group_id: str, payload: NotificationSettingsPayload) -> dict[str, Any]:
    destination_ids = list(dict.fromkeys(payload.destination_ids))
    with connection() as conn:
        group_repo.set_channels(conn, group_id, payload.qq_enabled, payload.email_enabled)
        notification_repo.clear_group(conn, group_id)
        for destination_id in destination_ids:
            notification_repo.bind_group(conn, group_id, destination_id)
    return {"saved": True, "revision": bump_config_revision()}


@router.post("/notification-settings/bulk-apply")
def bulk_apply_notification_settings(payload: NotificationBulkApply) -> dict[str, Any]:
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    if not group_ids:
        raise HTTPException(status_code=422, detail="at least one group is required")
    destination_ids = list(dict.fromkeys(payload.destination_ids))
    with connection() as conn:
        for group_id in group_ids:
            group_repo.set_channels(conn, group_id, payload.qq_enabled, payload.email_enabled)
            notification_repo.clear_group(conn, group_id)
            for destination_id in destination_ids:
                notification_repo.bind_group(conn, group_id, destination_id)
    return {"applied": len(group_ids), "revision": bump_config_revision()}