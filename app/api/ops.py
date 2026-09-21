"""Operations routes: NapCat control and container service management."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.api.deps import admin_guard, napcat
from app.control import DockerControl
from app.napcat import NapCatClient
from app.settings import Settings, get_settings


router = APIRouter(prefix="/api/ops", tags=["ops"], dependencies=[Depends(admin_guard)])


@router.get("/napcat/login")
async def napcat_login(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.login_status()


@router.post("/napcat/qrcode")
async def napcat_qrcode(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.qrcode()


@router.post("/napcat/qrcode/refresh")
async def napcat_qrcode_refresh(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.refresh_qrcode()


@router.get("/napcat/info")
async def napcat_info(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.login_info()


@router.get("/napcat/quick-login")
async def napcat_quick_login_list(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.quick_login_list()


@router.post("/napcat/quick-login")
async def napcat_quick_login(
    payload: dict[str, Any] = Body(default_factory=dict),
    client: NapCatClient = Depends(napcat),
) -> Any:
    return await client.quick_login(payload)


@router.post("/napcat/password-login")
async def napcat_password_login(
    payload: dict[str, Any] = Body(default_factory=dict),
    client: NapCatClient = Depends(napcat),
    settings: Settings = Depends(get_settings),
) -> Any:
    if not settings.napcat_password_login_enabled:
        raise HTTPException(status_code=403, detail="password login is disabled")
    return await client.password_login(payload)


@router.post("/napcat/restart")
async def napcat_restart(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.restart()


@router.post("/napcat/logout")
async def napcat_logout(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.logout()


@router.post("/napcat/process-restart")
async def napcat_process_restart(client: NapCatClient = Depends(napcat)) -> Any:
    return await client.restart_process()


@router.post("/services/{service}/restart")
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


@router.get("/logs/{service}")
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
