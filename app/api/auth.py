"""Authentication routes: login / logout / session probe."""
from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import session_token, valid_session
from app.schemas.auth import AdminLoginPayload
from app.settings import Settings, get_settings


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def auth_login(payload: AdminLoginPayload, response: Response, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    if not hmac.compare_digest(payload.token, settings.admin_token):
        raise HTTPException(status_code=401, detail="unauthorized")
    token = session_token(settings)
    response.set_cookie(
        "qq_bot_session", token, max_age=settings.auth_session_ttl,
        httponly=True, secure=settings.app_env == "prod", samesite="lax", path="/",
    )
    return {"authenticated": True}


@router.post("/logout")
def auth_logout(response: Response) -> dict[str, Any]:
    response.delete_cookie("qq_bot_session", path="/")
    return {"authenticated": False}


@router.get("/me")
def auth_me(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    authenticated = settings.app_env == "dev" or valid_session(request.cookies.get("qq_bot_session", ""), settings)
    if not authenticated:
        raise HTTPException(status_code=401, detail="unauthorized")
    return {"authenticated": True}
