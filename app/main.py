"""FastAPI application entrypoint.

Business logic lives in ``app/api/*`` routers; this module only wires the
application together (middleware, startup, routers, static frontend).
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    audit,
    auth,
    broadcast,
    dashboard,
    groups,
    health,
    history,
    keywords,
    notifications,
    ops,
    settings as settings_routes,
    uploads,
)
from app.db import connection, init_db
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


for router in (
    auth.router,
    health.router,
    settings_routes.router,
    groups.router,
    notifications.router,
    keywords.router,
    history.router,
    broadcast.router,
    dashboard.router,
    uploads.router,
    audit.router,
    ops.router,
):
    app.include_router(router)


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
