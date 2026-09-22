"""Release notes: the newest commits of the upstream repo, fetched server-side.

The browser used to call ``api.github.com`` directly, which fails two ways:
unauthenticated GitHub allows only 60 requests/hour per IP (a shared egress IP
exhausts that quickly and returns 403), and some networks cannot reach
``api.github.com`` at all even when ``github.com`` loads. Fetching from the
control plane gives us a dedicated quota, and the short cache keeps several
open consoles down to a single upstream request.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from app.api.deps import admin_guard

REPO = "XtSilan/QQkeywordForward"
PAGE_SIZE = 15
TIMEOUT_SECONDS = 8
CACHE_TTL_SECONDS = 600
API_URL = f"https://api.github.com/repos/{REPO}/commits"

router = APIRouter(prefix="/api", tags=["releases"], dependencies=[Depends(admin_guard)])

_items: list[dict[str, str]] = []
_cached_at = 0.0


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse(item: Any) -> dict[str, str] | None:
    """A commit message is "title line + body"; both become one entry."""
    entry = _dict(item)
    sha = str(entry.get("sha") or "")
    commit = _dict(entry.get("commit"))
    message = str(commit.get("message") or "")
    if not sha or not message.strip():
        return None
    lines = message.split("\n")
    return {
        "sha": sha,
        "time": str(_dict(commit.get("author")).get("date") or ""),
        "title": lines[0].strip(),
        "body": "\n".join(lines[1:]).strip(),
    }


@router.get("/release-notes")
async def release_notes() -> dict[str, Any]:
    """Cached newest commits.

    An unreachable or rate-limited GitHub never raises: the caller gets
    ``ok=False`` plus whatever was cached, so the UI can say "unavailable"
    instead of silently pretending there are no updates.
    """
    global _items, _cached_at
    now = time.monotonic()
    if _items and now - _cached_at < CACHE_TTL_SECONDS:
        return {"items": _items, "ok": True}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(
                API_URL,
                params={"per_page": PAGE_SIZE},
                headers={"Accept": "application/vnd.github+json"},
            )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {"items": _items, "ok": False}
    entries = [_parse(item) for item in payload] if isinstance(payload, list) else []
    parsed = [entry for entry in entries if entry is not None]
    if parsed:
        _items = parsed
        _cached_at = now
    return {"items": parsed, "ok": True}