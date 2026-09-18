import re
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.control import DockerControl
from app.db import bump_config_revision, config_revision, connection, init_db
from app.napcat import NapCatClient
from app.settings import Settings, get_settings


app = FastAPI(title="QQ Bot Control Plane", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


def admin_guard(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.app_env == "dev":
        return
    expected = f"Bearer {settings.admin_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


def napcat(settings: Settings = Depends(get_settings)) -> NapCatClient:
    return NapCatClient(settings)


class GroupPayload(BaseModel):
    group_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=200)
    avatar_url: str = Field(default="", max_length=1000)


class KeywordCreate(BaseModel):
    display_text: str = Field(min_length=1, max_length=200)
    group_ids: list[str] = Field(default_factory=list)
    enabled: bool = False
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)


class KeywordUpdate(BaseModel):
    display_text: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)


class KeywordBulkApply(BaseModel):
    keyword_id: int
    group_ids: list[str] = Field(min_length=1)
    enabled: bool = False
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "revision": config_revision()}


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
            "r.updated_at, COUNT(DISTINCT b.group_id) AS group_count "
            "FROM keyword_rules r LEFT JOIN group_keyword_bindings b "
            "ON b.keyword_id = r.id AND b.enabled = 1 "
            "WHERE r.deleted_at IS NULL "
            "AND (? IS NULL OR EXISTS (SELECT 1 FROM group_keyword_bindings gb "
            "WHERE gb.keyword_id = r.id AND gb.group_id = ?)) "
            "GROUP BY r.id ORDER BY r.updated_at DESC, r.id DESC",
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
    return result


@app.post("/api/keywords", dependencies=[Depends(admin_guard)])
def create_keyword(payload: KeywordCreate) -> dict[str, Any]:
    display_text = payload.display_text.strip()
    if not display_text:
        raise HTTPException(status_code=422, detail="display_text cannot be blank")
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    try:
        with connection() as conn:
            cursor = conn.execute(
                "INSERT INTO keyword_rules(display_text, pattern, match_mode, ignore_case, updated_at) "
                "VALUES (?, ?, 'literal_search', 1, CURRENT_TIMESTAMP)",
                (display_text, re.escape(display_text)),
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
        if service == "napcat" and (settings.napcat_webui_credential or settings.napcat_webui_token):
            data = await client.log_list()
            return PlainTextResponse(str(data))
        return PlainTextResponse(await DockerControl(settings).logs(service, tail))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


frontend = Path(__file__).resolve().parent.parent / "web" / "dist"
if frontend.exists():
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str) -> FileResponse:
        candidate = frontend / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend / "index.html")
