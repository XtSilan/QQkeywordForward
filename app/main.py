import re
import json
import uuid
import hmac
import hashlib
import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.control import DockerControl
from app.db import bump_config_revision, config_revision, connection, init_db
from app.napcat import NapCatClient
from app.schemas.auth import AdminLoginPayload
from app.schemas.broadcast import BroadcastTaskCreate, BroadcastTaskPatch
from app.schemas.group import GroupPayload
from app.schemas.keyword import (
    KeywordBulkApply,
    KeywordBulkUpdate,
    KeywordConfigCreate,
    KeywordCreate,
    KeywordNotificationUpdate,
    KeywordReorder,
    KeywordUpdate,
)
from app.schemas.notification import (
    DestinationCreate,
    DestinationUpdate,
    NotificationBulkApply,
    NotificationChannelPayload,
    NotificationConfigCreate,
    NotificationSettingsPayload,
)
from app.schemas.settings import (
    DuplicateMessageSettingsPayload,
    OneBotWebsocketPayload,
    SmtpSettingsPayload,
)
from app.settings import Settings, get_settings


app = FastAPI(title="QQ Bot Control Plane", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def audit_mutations(request: Request, call_next):
    response = await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
        authorization = request.headers.get("authorization", "")
        actor = "bearer" if authorization.startswith("Bearer ") else "session"
        resource = request.url.path.rstrip("/").split("/")[-1] or "root"
        try:
            with connection() as conn:
                conn.execute(
                    "INSERT INTO audit_logs(actor, action, resource_type, resource_id, detail_json, status_code) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (actor, request.method, request.url.path, resource, json.dumps({"path": request.url.path}), response.status_code),
                )
        except Exception:
            pass
    return response


@app.on_event("startup")
async def startup() -> None:
    init_db()
    settings = get_settings()
    # Auto-push ONEBOT_WS_URL into NapCat once QQ is logged in so users don't
    # have to open the WebUI to wire up the reverse-WS client.
    if settings.onebot_ws_url:
        asyncio.create_task(_auto_apply_onebot_config(settings))


async def _auto_apply_onebot_config(settings: Settings) -> None:
    client = NapCatClient(settings)
    while True:
        try:
            status = await client.login_status()
            if isinstance(status, dict) and status.get("isLogin"):
                config = await client.onebot_config()
                network = (config if isinstance(config, dict) else {}).setdefault("network", {})
                clients = network.setdefault("websocketClients", [])
                item = next((value for value in clients if value.get("name") == "websocket-client"), None)
                if item is None:
                    item = {
                        "name": "websocket-client",
                        "messagePostFormat": "array",
                        "reportSelfMessage": False,
                        "debug": False,
                        "heartInterval": 30000,
                        "reconnectInterval": 5000,
                    }
                    clients.append(item)
                # Only push when missing or mismatched; avoids fighting a user
                # who manually customised other fields in the NapCat WebUI.
                if item.get("url") != settings.onebot_ws_url or not item.get("enable"):
                    item["enable"] = True
                    item["url"] = settings.onebot_ws_url
                    if settings.onebot_access_token:
                        item["token"] = settings.onebot_access_token
                    await client.set_onebot_config(config)
        except Exception:
            pass
        await asyncio.sleep(30)


def admin_guard(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.app_env == "dev":
        return
    if authorization and authorization.startswith("Bearer ") and hmac.compare_digest(authorization[7:], settings.admin_token):
        return
    session = request.cookies.get("qq_bot_session", "")
    if _valid_session(session, settings):
        return
    raise HTTPException(status_code=401, detail="unauthorized")


def _session_token(settings: Settings, timestamp: int | None = None) -> str:
    timestamp = timestamp or int(time.time())
    value = str(timestamp)
    signature = hmac.new(settings.auth_session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def _valid_session(token: str, settings: Settings) -> bool:
    try:
        timestamp_text, signature = token.split(".", 1)
        timestamp = int(timestamp_text)
    except (ValueError, TypeError):
        return False
    if abs(int(time.time()) - timestamp) > settings.auth_session_ttl:
        return False
    expected = hmac.new(settings.auth_session_secret.encode(), timestamp_text.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@app.post("/api/auth/login")
def auth_login(payload: AdminLoginPayload, response: Response, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    if not hmac.compare_digest(payload.token, settings.admin_token):
        raise HTTPException(status_code=401, detail="unauthorized")
    token = _session_token(settings)
    response.set_cookie(
        "qq_bot_session", token, max_age=settings.auth_session_ttl,
        httponly=True, secure=settings.app_env == "prod", samesite="lax", path="/",
    )
    return {"authenticated": True}


@app.post("/api/auth/logout")
def auth_logout(response: Response) -> dict[str, Any]:
    response.delete_cookie("qq_bot_session", path="/")
    return {"authenticated": False}


@app.get("/api/auth/me")
def auth_me(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    authenticated = settings.app_env == "dev" or _valid_session(request.cookies.get("qq_bot_session", ""), settings)
    if not authenticated:
        raise HTTPException(status_code=401, detail="unauthorized")
    return {"authenticated": True}


def napcat(settings: Settings = Depends(get_settings)) -> NapCatClient:
    return NapCatClient(settings)


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row)


@app.get("/api/settings/duplicate-message-cooling", dependencies=[Depends(admin_guard)])
def get_duplicate_message_cooling() -> dict[str, int]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM app_meta WHERE key IN "
            "('duplicate_message_threshold', 'duplicate_message_cooldown_seconds')"
        ).fetchall()
    values = {str(row["key"]): str(row["value"]) for row in rows}
    return {
        "threshold": int(values.get("duplicate_message_threshold", "2")),
        "cooldown_minutes": max(
            1, int(values.get("duplicate_message_cooldown_seconds", "600")) // 60
        ),
    }


@app.put("/api/settings/duplicate-message-cooling", dependencies=[Depends(admin_guard)])
def put_duplicate_message_cooling(payload: DuplicateMessageSettingsPayload) -> dict[str, Any]:
    values = {
        "duplicate_message_threshold": str(payload.threshold),
        "duplicate_message_cooldown_seconds": str(payload.cooldown_minutes * 60),
    }
    with connection() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
    return {"saved": True, **payload.model_dump(), "revision": bump_config_revision()}


@app.get("/api/settings/smtp", dependencies=[Depends(admin_guard)])
def get_smtp_settings(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    with connection() as conn:
        overrides = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM app_meta WHERE key LIKE 'smtp_%'")}
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


@app.put("/api/settings/smtp", dependencies=[Depends(admin_guard)])
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
        for key, value in values.items():
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
    return {"saved": True, "password_configured": bool(payload.password), "revision": bump_config_revision()}


@app.get("/api/settings/onebot", dependencies=[Depends(admin_guard)])
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


@app.put("/api/settings/onebot", dependencies=[Depends(admin_guard)])
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


@app.post("/api/notifications/test", dependencies=[Depends(admin_guard)])
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


@app.get("/api/audit-logs", dependencies=[Depends(admin_guard)])
def audit_logs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, actor, action, resource_type, resource_id, detail_json, status_code, created_at "
            "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_dict(row) for row in rows]


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "revision": config_revision()}


@app.post("/api/uploads/image", dependencies=[Depends(admin_guard)])
async def upload_image(file: UploadFile = File(...), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
    suffix = allowed.get(file.content_type or "")
    if not suffix:
        raise HTTPException(status_code=415, detail="只支持 JPG、PNG、GIF、WEBP 图片")
    limit = settings.max_upload_size_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {settings.max_upload_size_mb}MB")
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    (upload_dir / filename).write_bytes(data)
    url = settings.public_base_url.rstrip("/") + "/media/" + filename
    return {"url": url, "segment": {"type": "image", "data": {"file": url}}}


@app.get("/api/dashboard", dependencies=[Depends(admin_guard)])
async def dashboard(
    client: NapCatClient = Depends(napcat),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    status: Any = {"ok": False, "error": "not configured"}
    if settings.napcat_webui_credential or settings.napcat_webui_token:
        try:
            status = await client.login_status()
        except Exception as exc:
            status = {"ok": False, "error": str(exc)}
    return {
        "config_revision": config_revision(),
        "napcat": status,
        "nonebot": {"service": "nonebot", "config_reload": True},
        "stats": {
            "groups": _count("groups"),
            "keyword_hits_today": _count(
                "keyword_hits", "hit_at >= datetime('now', 'start of day')"
            ),
        },
    }


def _count(table: str, where: str = "1=1") -> int:
    if table not in {"groups", "keyword_hits"}:
        raise ValueError("unsupported table")
    with connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}").fetchone()
        return int(row["count"])


@app.get("/api/groups", dependencies=[Depends(admin_guard)])
def groups() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT group_id, name, avatar_url, enabled, last_synced_at "
            "FROM groups ORDER BY name COLLATE NOCASE, group_id"
        ).fetchall()
    return [row_dict(row) for row in rows]


@app.post("/api/groups/sync", dependencies=[Depends(admin_guard)])
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


@app.get("/api/keywords", dependencies=[Depends(admin_guard)])
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


@app.post("/api/keywords", dependencies=[Depends(admin_guard)])
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


@app.post("/api/keyword-configs", dependencies=[Depends(admin_guard)])
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


@app.patch("/api/keywords/{keyword_id}", dependencies=[Depends(admin_guard)])
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


@app.post("/api/keywords/bulk-toggle", dependencies=[Depends(admin_guard)])
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


@app.post("/api/keywords/bulk-delete", dependencies=[Depends(admin_guard)])
def bulk_delete_keywords(payload: KeywordBulkUpdate) -> dict[str, Any]:
    with connection() as conn:
        placeholders = ",".join("?" for _ in payload.keyword_ids)
        conn.execute(
            f"UPDATE keyword_rules SET deleted_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            tuple(payload.keyword_ids),
        )
    return {"deleted": len(payload.keyword_ids), "revision": bump_config_revision()}


@app.post("/api/keywords/reorder", dependencies=[Depends(admin_guard)])
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


@app.put("/api/keywords/{keyword_id}/notifications", dependencies=[Depends(admin_guard)])
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


@app.delete("/api/keywords/{keyword_id}", dependencies=[Depends(admin_guard)])
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


@app.post("/api/keywords/bulk-apply", dependencies=[Depends(admin_guard)])
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


@app.get("/api/history", dependencies=[Depends(admin_guard)])
def history(
    group_id: str | None = Query(default=None),
    keyword_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, group_id, group_name, sender_id, sender_name, keyword_id, "
            "keyword_text_snapshot, message_text, message_id, hit_at, notify_status "
            "FROM keyword_hits WHERE (? IS NULL OR group_id=?) "
            "AND (? IS NULL OR keyword_id=?) ORDER BY hit_at DESC LIMIT ? OFFSET ?",
            (group_id, group_id, keyword_id, keyword_id, limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM keyword_hits WHERE (? IS NULL OR group_id=?) "
            "AND (? IS NULL OR keyword_id=?)",
            (group_id, group_id, keyword_id, keyword_id),
        ).fetchone()["count"]
    return {"items": [row_dict(row) for row in rows], "total": int(total), "limit": limit, "offset": offset}


@app.get("/api/destinations", dependencies=[Depends(admin_guard)])
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


@app.post("/api/destinations", dependencies=[Depends(admin_guard)])
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


@app.post("/api/notification-configs", dependencies=[Depends(admin_guard)])
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


@app.put("/api/destinations/{destination_id}", dependencies=[Depends(admin_guard)])
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


@app.delete("/api/destinations/{destination_id}", dependencies=[Depends(admin_guard)])
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


@app.get("/api/groups/{group_id}/notification-settings", dependencies=[Depends(admin_guard)])
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


@app.put("/api/groups/{group_id}/notification-settings", dependencies=[Depends(admin_guard)])
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


@app.post("/api/notification-settings/bulk-apply", dependencies=[Depends(admin_guard)])
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


@app.get("/api/broadcast-tasks", dependencies=[Depends(admin_guard)])
def broadcast_tasks(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, title, interval_seconds, group_cooldown_seconds, status, total_count, "
            "sent_count, failed_count, created_at, started_at, finished_at "
            "FROM broadcast_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [row_dict(row) for row in rows]


@app.post("/api/broadcast-tasks", dependencies=[Depends(admin_guard)])
def create_broadcast_task(payload: BroadcastTaskCreate) -> dict[str, Any]:
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    if not group_ids:
        raise HTTPException(status_code=422, detail="at least one group is required")
    task_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with connection() as conn:
        for group_id in group_ids:
            conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
        conn.execute(
            "INSERT INTO broadcast_tasks(id, title, message_json, interval_seconds, group_cooldown_seconds, "
            "status, total_count, created_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)",
            (task_id, payload.title.strip(), json.dumps(payload.message, ensure_ascii=False), payload.interval_seconds,
             payload.group_cooldown_seconds, len(group_ids), now.isoformat()),
        )
        for index, group_id in enumerate(group_ids):
            conn.execute(
                "INSERT INTO broadcast_task_groups(task_id, group_id, scheduled_at) VALUES (?, ?, ?)",
                (task_id, group_id, (now + timedelta(seconds=index * payload.interval_seconds)).isoformat()),
            )
    return {"id": task_id, "status": "queued", "total_count": len(group_ids), "revision": bump_config_revision()}


@app.get("/api/broadcast-tasks/{task_id}", dependencies=[Depends(admin_guard)])
def broadcast_task(task_id: str) -> dict[str, Any]:
    with connection() as conn:
        task = conn.execute("SELECT * FROM broadcast_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        groups = conn.execute(
            "SELECT task_id, group_id, status, scheduled_at, sent_at, message_id, error_code, error_text, attempts "
            "FROM broadcast_task_groups WHERE task_id=? ORDER BY scheduled_at",
            (task_id,),
        ).fetchall()
    result = row_dict(task)
    result["message"] = json.loads(result.pop("message_json"))
    result["groups"] = [row_dict(group) for group in groups]
    return result


@app.post("/api/broadcast-tasks/{task_id}/cancel", dependencies=[Depends(admin_guard)])
def cancel_broadcast_task(task_id: str) -> dict[str, Any]:
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE broadcast_tasks SET status='cancelled', cancelled_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status IN ('draft', 'queued', 'running', 'paused')",
            (task_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="active task not found")
        conn.execute(
            "UPDATE broadcast_task_groups SET status='cancelled' WHERE task_id=? AND status IN ('queued','paused')",
            (task_id,),
        )
    return {"cancelled": True, "revision": bump_config_revision()}


@app.post("/api/broadcast-tasks/{task_id}/pause", dependencies=[Depends(admin_guard)])
def pause_broadcast_task(task_id: str) -> dict[str, Any]:
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE broadcast_tasks SET status='paused' "
            "WHERE id=? AND status IN ('queued', 'running')",
            (task_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="running task not found")
        conn.execute(
            "UPDATE broadcast_task_groups SET status='paused' WHERE task_id=? AND status='queued'",
            (task_id,),
        )
    return {"paused": True, "revision": bump_config_revision()}


@app.post("/api/broadcast-tasks/{task_id}/resume", dependencies=[Depends(admin_guard)])
def resume_broadcast_task(task_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with connection() as conn:
        task = conn.execute(
            "SELECT interval_seconds FROM broadcast_tasks WHERE id=? AND status='paused'",
            (task_id,),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="paused task not found")
        interval = task["interval_seconds"]
        conn.execute(
            "UPDATE broadcast_tasks SET status='running' WHERE id=?",
            (task_id,),
        )
        # Re-schedule remaining queued groups starting from now so a long pause
        # doesn't trigger a catch-up burst.
        queued = conn.execute(
            "SELECT group_id FROM broadcast_task_groups WHERE task_id=? AND status='paused' ORDER BY scheduled_at",
            (task_id,),
        ).fetchall()
        for index, row in enumerate(queued):
            conn.execute(
                "UPDATE broadcast_task_groups SET status='queued', scheduled_at=? "
                "WHERE task_id=? AND group_id=?",
                ((now + timedelta(seconds=index * interval)).isoformat(), task_id, row["group_id"]),
            )
    return {"resumed": True, "interval_seconds": interval, "revision": bump_config_revision()}


class BroadcastTaskPatch(BaseModel):
    interval_seconds: int | None = Field(default=None, ge=5)


@app.patch("/api/broadcast-tasks/{task_id}", dependencies=[Depends(admin_guard)])
def patch_broadcast_task(task_id: str, payload: BroadcastTaskPatch) -> dict[str, Any]:
    if payload.interval_seconds is None:
        raise HTTPException(status_code=422, detail="no fields to update")
    now = datetime.now(timezone.utc)
    with connection() as conn:
        task = conn.execute(
            "SELECT status, interval_seconds FROM broadcast_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        if task["status"] not in ("queued", "running", "paused"):
            raise HTTPException(status_code=409, detail=f"cannot adjust task in status {task['status']}")
        conn.execute(
            "UPDATE broadcast_tasks SET interval_seconds=? WHERE id=?",
            (payload.interval_seconds, task_id),
        )
        # Re-schedule queued groups by the new interval so the change is visible
        # immediately. Paused groups will be re-scheduled on resume.
        queued = conn.execute(
            "SELECT group_id FROM broadcast_task_groups WHERE task_id=? AND status='queued' ORDER BY scheduled_at",
            (task_id,),
        ).fetchall()
        for index, row in enumerate(queued):
            conn.execute(
                "UPDATE broadcast_task_groups SET scheduled_at=? WHERE task_id=? AND group_id=?",
                ((now + timedelta(seconds=index * payload.interval_seconds)).isoformat(), task_id, row["group_id"]),
            )
    return {"interval_seconds": payload.interval_seconds, "revision": bump_config_revision()}


@app.get("/api/ops/napcat/login", dependencies=[Depends(admin_guard)])
async def napcat_login(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.login_status()


@app.post("/api/ops/napcat/qrcode", dependencies=[Depends(admin_guard)])
async def napcat_qrcode(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.qrcode()


@app.post("/api/ops/napcat/qrcode/refresh", dependencies=[Depends(admin_guard)])
async def napcat_qrcode_refresh(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.refresh_qrcode()


@app.get("/api/ops/napcat/info", dependencies=[Depends(admin_guard)])
async def napcat_info(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.login_info()


@app.get("/api/ops/napcat/quick-login", dependencies=[Depends(admin_guard)])
async def napcat_quick_login_list(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.quick_login_list()


@app.post("/api/ops/napcat/quick-login", dependencies=[Depends(admin_guard)])
async def napcat_quick_login(
    payload: dict[str, Any] = Body(default_factory=dict),
    client: NapCatClient = Depends(napcat),
) -> Any:
    return await client.quick_login(payload)


@app.post("/api/ops/napcat/password-login", dependencies=[Depends(admin_guard)])
async def napcat_password_login(
    payload: dict[str, Any] = Body(default_factory=dict),
    client: NapCatClient = Depends(napcat),
    settings: Settings = Depends(get_settings),
) -> Any:
    if not settings.napcat_password_login_enabled:
        raise HTTPException(status_code=403, detail="password login is disabled")
    return await client.password_login(payload)


@app.post("/api/ops/napcat/restart", dependencies=[Depends(admin_guard)])
async def napcat_restart(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.restart()


@app.post("/api/ops/napcat/process-restart", dependencies=[Depends(admin_guard)])
async def napcat_process_restart(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.restart_process()


@app.post("/api/ops/services/{service}/restart", dependencies=[Depends(admin_guard)])
async def service_restart(
    service: str,
    settings: Settings = Depends(get_settings),
) -> Any:
    try:
        return await DockerControl(settings).restart(service)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/ops/logs/{service}", dependencies=[Depends(admin_guard)])
async def service_logs(
    service: str,
    tail: int = Query(default=200, ge=1, le=2000),
    settings: Settings = Depends(get_settings),
    client: NapCatClient = Depends(napcat),
) -> PlainTextResponse:
    try:
        # NapCat's WebUI log list is a metadata endpoint and may be empty even while
        # the container is producing logs. The Docker log stream is the authoritative
        # source for the WebUI log panel when socket control is enabled.
        if settings.control_enabled:
            return PlainTextResponse(await DockerControl(settings).logs(service, tail))
        if service == "napcat" and (settings.napcat_webui_credential or settings.napcat_webui_token):
            listing = await client.log_list()
            if not isinstance(listing, list) or not listing:
                return PlainTextResponse("NapCat 没有返回文件日志；请启用 Docker socket 日志读取。")
            latest = listing[-1]
            if isinstance(latest, dict):
                filename = latest.get("id") or latest.get("name") or latest.get("filename")
            else:
                filename = str(latest)
            if not filename:
                return PlainTextResponse("NapCat 日志文件名为空；请启用 Docker socket 日志读取。")
            return PlainTextResponse(str(await client.log_file(str(filename))))
        return PlainTextResponse(await DockerControl(settings).logs(service, tail))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


frontend = Path(__file__).resolve().parent.parent / "web" / "dist"
upload_path = Path(get_settings().upload_dir)
upload_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=upload_path), name="media")
if frontend.exists():
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str) -> FileResponse:
        candidate = frontend / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend / "index.html")
