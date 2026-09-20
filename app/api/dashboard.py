"""Dashboard summary route."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import admin_guard, napcat
from app.db import config_revision, connection
from app.napcat import NapCatClient
from app.settings import Settings, get_settings


router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(admin_guard)])


def _count(table: str, where: str = "1=1") -> int:
    if table not in {"groups", "keyword_hits"}:
        raise ValueError("unsupported table")
    with connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}").fetchone()
        return int(row["count"])


@router.get("/dashboard")
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
