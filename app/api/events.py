"""Server-sent event stream feeding the live parts of the UI.

The sender lives in the *nonebot* container while these routes are served by the
*webui* container, so there is no in-process event bus to broadcast from. This
endpoint therefore re-reads SQLite on a short interval and only emits when the
resulting snapshot actually changed, which gives the browser push semantics
without any cross-container messaging.

Only database-derived state is streamed. Anything that requires calling NapCat
(dashboard service status) stays on its own slower poll.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import admin_guard
from app.db import connection
from app.repositories import broadcast_repo


router = APIRouter(prefix="/api", tags=["events"], dependencies=[Depends(admin_guard)])

SNAPSHOT_INTERVAL_SECONDS = 1.0
# Comment-only frame so idle connections survive proxies that drop silent ones.
KEEP_ALIVE_SECONDS = 15.0
TASK_LIMIT = 20


def _snapshot() -> dict[str, Any]:
    with connection() as conn:
        tasks = broadcast_repo.list_tasks(conn, TASK_LIMIT)
        hits = conn.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(MAX(id), 0) AS latest_id, "
            "COALESCE(SUM(hit_at >= datetime('now', 'start of day')), 0) AS today "
            "FROM keyword_hits"
        ).fetchone()
        groups = conn.execute("SELECT COUNT(*) AS count FROM groups").fetchone()
        revision = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'config_revision'"
        ).fetchone()
    return {
        "revision": int(revision["value"]) if revision else 0,
        "groups": int(groups["count"]),
        "hits": {
            "total": int(hits["total"]),
            "today": int(hits["today"]),
            "latest_id": int(hits["latest_id"]),
        },
        "tasks": tasks,
    }


async def _event_stream() -> AsyncIterator[str]:
    last_payload = ""
    last_sent_at = 0.0
    while True:
        try:
            payload = json.dumps(_snapshot(), ensure_ascii=False)
        except Exception:
            payload = ""
        now = asyncio.get_running_loop().time()
        if payload and payload != last_payload:
            last_payload = payload
            last_sent_at = now
            yield f"event: snapshot\ndata: {payload}\n\n"
        elif now - last_sent_at >= KEEP_ALIVE_SECONDS:
            last_sent_at = now
            yield ": keep-alive\n\n"
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)


@router.get("/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tell nginx-style proxies not to buffer, otherwise events batch up.
            "X-Accel-Buffering": "no",
        },
    )