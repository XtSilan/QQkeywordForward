"""Application settings routes: duplicate-message cooling, SMTP, OneBot WS.

HTTP/validation concerns only — the app_meta key/value access lives in
``app.repositories.meta_repo``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import admin_guard, napcat
from app.db import bump_config_revision, connection
from app.napcat import NapCatClient
from app.repositories import meta_repo
from app.schemas.settings import (
    DuplicateMessageSettingsPayload,
    OneBotWebsocketPayload,
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


@router.get("/onebot")
async def get_onebot_settings(client: NapCatClient = Depends(napcat)) -> dict[str, Any]:
    try:
        config = await client.onebot_config()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"NapCat OneBot 配置不可用: {exc}") from exc
    clients = (config.get("network", {}) if isinstance(config, dict) else {}).get("websocketClients", [])
    item = next((value for value in clients if value.get("name") == "websocket-client"), clients[0] if clients else {})
    return {"websocket_client": {
        "name": item.get("name", "websocket-client"), "enable": bool(item.get("enable", False)),
        "url": item.get("url", ""), "reconnectInterval": item.get("reconnectInterval", 5000),
        "heartInterval": item.get("heartInterval", 30000), "verifyCertificate": item.get("verifyCertificate", True),
        "token_configured": bool(item.get("token")),
    }}


@router.put("/onebot")
async def put_onebot_settings(payload: OneBotWebsocketPayload, client: NapCatClient = Depends(napcat)) -> dict[str, Any]:
    try:
        config = await client.onebot_config()
        network = config.setdefault("network", {})
        clients = network.setdefault("websocketClients", [])
        item = next((value for value in clients if value.get("name") == "websocket-client"), None)
        if item is None:
            item = {"name": "websocket-client", "messagePostFormat": "array", "reportSelfMessage": False, "debug": False}
            clients.append(item)
        item.update({"enable": payload.enable, "url": payload.url, "reconnectInterval": payload.reconnectInterval,
                    "heartInterval": payload.heartInterval, "verifyCertificate": payload.verifyCertificate})
        if payload.token is not None:
            item["token"] = payload.token
        await client.set_onebot_config(config)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OneBot 配置写入失败: {exc}") from exc
    return {"saved": True, "restart_required": True, "revision": bump_config_revision()}