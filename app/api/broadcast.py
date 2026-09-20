"""Broadcast task routes: CRUD, cancel/pause/resume, speed adjustment."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import admin_guard, row_dict
from app.db import bump_config_revision, connection
from app.schemas.broadcast import BroadcastTaskCreate, BroadcastTaskPatch


router = APIRouter(
    prefix="/api/broadcast-tasks",
    tags=["broadcast"],
    dependencies=[Depends(admin_guard)],
)


@router.get("")
def broadcast_tasks(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, title, interval_seconds, group_cooldown_seconds, status, total_count, "
            "sent_count, failed_count, created_at, started_at, finished_at "
            "FROM broadcast_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [row_dict(row) for row in rows]


@router.post("")
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


@router.get("/{task_id}")
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


@router.post("/{task_id}/cancel")
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


@router.post("/{task_id}/pause")
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


@router.post("/{task_id}/resume")
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


@router.patch("/{task_id}")
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