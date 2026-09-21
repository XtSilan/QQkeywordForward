"""Application settings routes: order-dedup alerting and SMTP.

HTTP/validation concerns only — the app_meta key/value access lives in
``app.repositories.meta_repo`` and the parsing defaults in
``app.services.orders``.

The NapCat OneBot reverse-WebSocket config is intentionally absent: it is
derived from ``ONEBOT_WS_URL`` / ``ONEBOT_ACCESS_TOKEN`` and pushed by
``app.services.napcat_sync``, so there is no manual override to edit here.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import admin_guard
from app.db import bump_config_revision, connection
from app.repositories import meta_repo
from app.schemas.settings import (
    AlertDedupSettingsPayload,
    AutoLoginSettingsPayload,
    SmtpSettingsPayload,
)
from app.services import orders as order_dedup
from app.settings import Settings, get_settings


router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(admin_guard)])


@router.get("/order-dedup")
def get_order_dedup_settings() -> dict[str, Any]:
    with connection() as conn:
        dedup = order_dedup.load_settings(conn)
    return {
        "enabled": dedup.enabled,
        "similarity": dedup.similarity,
        "window_minutes": int(dedup.window_seconds // 60),
        "max_push_per_order": dedup.max_push,
        "new_phone_repush": dedup.new_phone_repush,
        "ad_filter_enabled": dedup.ad_filter_enabled,
        "ad_keywords": ",".join(dedup.ad_keywords),
    }


@router.put("/order-dedup")
def put_order_dedup_settings(payload: AlertDedupSettingsPayload) -> dict[str, Any]:
    ad_keywords = ",".join(
        keyword.strip()
        for keyword in payload.ad_keywords.replace("，", ",").split(",")
        if keyword.strip()
    )
    with connection() as conn:
        meta_repo.set_many(conn, {
            "alert_dedup_enabled": "1" if payload.enabled else "0",
            "alert_similarity_threshold": str(payload.similarity),
            "alert_order_window_minutes": str(payload.window_minutes),
            "alert_max_push_per_order": str(payload.max_push_per_order),
            "alert_new_phone_repush": "1" if payload.new_phone_repush else "0",
            "alert_ad_filter_enabled": "1" if payload.ad_filter_enabled else "0",
            "alert_ad_keywords": ad_keywords,
        })
    return {"saved": True, **payload.model_dump(), "revision": bump_config_revision()}


@router.get("/auto-login")
def get_auto_login_settings(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    with connection() as conn:
        configured = meta_repo.get(conn, "auto_login_uin")
    return {
        # DB override wins; the env var is the bootstrap fallback.
        "uin": (configured if configured is not None else settings.quick_login_uin).strip(),
    }


@router.put("/auto-login")
def put_auto_login_settings(payload: AutoLoginSettingsPayload) -> dict[str, Any]:
    uin = payload.uin.strip()
    if uin and not uin.isdigit():
        raise HTTPException(status_code=400, detail="QQ 号只能是数字")
    with connection() as conn:
        meta_repo.set(conn, "auto_login_uin", uin)
    return {"saved": True, "uin": uin, "revision": bump_config_revision()}


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