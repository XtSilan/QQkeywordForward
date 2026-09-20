"""Broadcast task routes: CRUD, cancel/pause/resume.

HTTP/validation concerns only — data access delegates to
``app.repositories.broadcast_repo``.

Changing the group delay is deliberately only possible through ``resume``: a
running task cannot be re-spaced mid-flight, which keeps the schedule the user
sees identical to the schedule being executed.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import admin_guard
from app.db import bump_config_revision, connection
from app.repositories import broadcast_repo, group_repo
from app.schemas.broadcast import BroadcastResumePayload, BroadcastTaskCreate


router = APIRouter(
    prefix="/api/broadcast-tasks",
    tags=["broadcast"],
    dependencies=[Depends(admin_guard)],
)


@router.get("")
def broadcast_tasks(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    with connection() as conn:
        return broadcast_repo.list_tasks(conn, limit)


@router.post("")
def create_broadcast_task(payload: BroadcastTaskCreate) -> dict[str, Any]:
    group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.group_ids if group_id.strip()))
    if not group_ids:
        raise HTTPException(status_code=422, detail="at least one group is required")
    task_id = uuid.uuid4().hex
    with connection() as conn:
        for group_id in group_ids:
            group_repo.ensure_group(conn, group_id)
        broadcast_repo.create(
            conn, task_id, payload.title.strip(), payload.message,
            payload.interval_seconds, payload.group_cooldown_seconds, group_ids,
        )
    return {"id": task_id, "status": "queued", "total_count": len(group_ids), "revision": bump_config_revision()}


@router.get("/{task_id}")
def broadcast_task(task_id: str) -> dict[str, Any]:
    with connection() as conn:
        result = broadcast_repo.get_task(conn, task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="task not found")
    return result


@router.post("/{task_id}/cancel")
def cancel_broadcast_task(task_id: str) -> dict[str, Any]:
    with connection() as conn:
        if not broadcast_repo.cancel(conn, task_id):
            raise HTTPException(status_code=404, detail="active task not found")
    return {"cancelled": True, "revision": bump_config_revision()}


@router.post("/{task_id}/pause")
def pause_broadcast_task(task_id: str) -> dict[str, Any]:
    with connection() as conn:
        if not broadcast_repo.pause(conn, task_id):
            raise HTTPException(status_code=404, detail="running task not found")
    return {"paused": True, "revision": bump_config_revision()}


@router.post("/{task_id}/resume")
def resume_broadcast_task(
    task_id: str,
    payload: BroadcastResumePayload | None = None,
) -> dict[str, Any]:
    """Resume a paused task, optionally under a new group delay.

    Passing ``interval_seconds`` lets the UI do "pause, retune, confirm" in one
    atomic step instead of a PATCH followed by a separate resume.
    """
    with connection() as conn:
        # ``paused_interval`` doubles as the guard: it returns None unless the
        # task really is paused, so an explicit delay cannot revive a finished
        # or cancelled task.
        stored = broadcast_repo.paused_interval(conn, task_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="paused task not found")
        interval = payload.interval_seconds if payload and payload.interval_seconds else stored
        broadcast_repo.resume(conn, task_id, interval)
    return {"resumed": True, "interval_seconds": interval, "revision": bump_config_revision()}