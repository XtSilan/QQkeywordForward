from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.control import DockerControl
from app.db import config_revision, init_db
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
    }


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
