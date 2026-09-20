"""Application settings routes: duplicate-message cooling and SMTP.

HTTP/validation concerns only — the app_meta key/value access lives in
``app.repositories.meta_repo``.

The NapCat OneBot reverse-WebSocket config is intentionally absent: it is
derived from ``ONEBOT_WS_URL`` / ``ONEBOT_ACCESS_TOKEN`` and pushed by
``app.services.napcat_sync``, so there is no manual override to edit here.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import admin_guard
from app.db import bump_config_revision, connection
from app.repositories import meta_repo
from app.schemas.settings import (
    DuplicateMessageSettingsPayload,
    SmtpSettingsPayload,
)
from app.settings import Settings, get_settings


router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(admin_guard)])


@router.get("/duplicate-message-cooling")
def get_duplicate_message_cooling() -> dict[str, int]:
    with connection() as conn:
        values = meta_repo.get_many(
            conn, ["duplicate_message_threshold", "duplicate_message_cooldown_seconds"]
        )
    return {
        "threshold": int(values.get("duplicate_message_threshold", "2")),
        "cooldown_minutes": max(
            1, int(values.get("duplicate_message_cooldown_seconds", "600")) // 60
        ),
    }


@router.put("/duplicate-message-cooling")
def put_duplicate_message_cooling(payload: DuplicateMessageSettingsPayload) -> dict[str, Any]:
    with connection() as conn:
        meta_repo.set_many(conn, {
            "duplicate_message_threshold": str(payload.threshold),
            "duplicate_message_cooldown_seconds": str(payload.cooldown_minutes * 60),
        })
    return {"saved": True, **payload.model_dump(), "revision": bump_config_revision()}


@router.get("/smtp")
def get_smtp_settings(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    with connection() as conn:
        overrides = meta_repo.get_by_prefix(conn, "smtp_")
    return {
        "host": overrides.get("smtp_host", settings.smtp_host),
        "port": int(overrides.get("smtp_port", settings.smtp_port)),
        "username": overrides.get("smtp_username", settings.smtp_username),
        "from_address": overrides.get("smtp_from", settings.smtp_from),
        "starttls": overrides.get("smtp_starttls", str(settings.smtp_starttls)).lower() == "true",
        "ssl": overrides.get("smtp_ssl", str(settings.smtp_ssl)).lower() == "true",
        "timeout": int(overrides.get("smtp_timeout", settings.smtp_timeout)),
        "password_configured": bool(overrides.get("smtp_password", settings.smtp_password)),
    }


@router.put("/smtp")
def put_smtp_settings(payload: SmtpSettingsPayload) -> dict[str, Any]:
    values = {
        "smtp_host": payload.host.strip(), "smtp_port": str(payload.port),
        "smtp_username": payload.username.strip(), "smtp_from": payload.from_address.strip(),
        "smtp_starttls": str(payload.starttls), "smtp_ssl": str(payload.ssl),
        "smtp_timeout": str(payload.timeout),
    }
    if payload.password:
        values["smtp_password"] = payload.password
    with connection() as conn:
        meta_repo.set_many(conn, values)
    return {"saved": True, "password_configured": bool(payload.password), "revision": bump_config_revision()}