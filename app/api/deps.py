"""Shared FastAPI dependencies and helpers used across routers."""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Depends, Header, HTTPException, Request

from app.napcat import NapCatClient
from app.settings import Settings, get_settings


def admin_guard(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject requests without a valid bearer token or session cookie."""
    if settings.app_env == "dev":
        return
    if authorization and authorization.startswith("Bearer ") and hmac.compare_digest(authorization[7:], settings.admin_token):
        return
    session = request.cookies.get("qq_bot_session", "")
    if valid_session(session, settings):
        return
    raise HTTPException(status_code=401, detail="unauthorized")


def napcat(settings: Settings = Depends(get_settings)) -> NapCatClient:
    return NapCatClient(settings)


def session_token(settings: Settings, timestamp: int | None = None) -> str:
    timestamp = timestamp or int(time.time())
    value = str(timestamp)
    signature = hmac.new(settings.auth_session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def valid_session(token: str, settings: Settings) -> bool:
    try:
        timestamp_text, signature = token.split(".", 1)
        timestamp = int(timestamp_text)
    except (ValueError, TypeError):
        return False
    if abs(int(time.time()) - timestamp) > settings.auth_session_ttl:
        return False
    expected = hmac.new(settings.auth_session_secret.encode(), timestamp_text.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
