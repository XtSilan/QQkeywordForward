"""Broadcast task routes: CRUD, cancel/pause/resume, interval retune.

HTTP/validation concerns only — data access delegates to
``app.repositories.broadcast_repo``.

Changing the *group* delay re-spaces work that may already be scheduled, so it
stays tied to a moment when nothing is in flight: either ``resume`` for a paused
task or the ``PUT`` route below, which also only accepts it while paused. The
round gap of an auto-looping task only decides when the next round starts, so it
can be retuned at any time.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import admin_guard
from app.db import bump_config_revision, connection
from app.repositories import broadcast_repo, group_repo
from app.schemas.broadcast import (
    BroadcastIntervalsPayload,
    BroadcastResumePayload,
    BroadcastTaskCreate,
)


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
        # 过滤掉已禁用的群（bot 已不在、手动禁用等）
        enabled_rows = conn.execute(
            "SELECT group_id FROM groups WHERE enabled=1 AND group_id IN ({})".format(
                ",".join("?" for _ in group_ids)
            ),
            tuple(group_ids),
        ).fetchall()
        enabled_ids = [r[0] for r in enabled_rows]
        skipped = len(group_ids) - len(enabled_ids)
        if not enabled_ids:
            raise HTTPException(status_code=422, detail="所有目标群已被禁用，无法群发")
        for group_id in enabled_ids:
            group_repo.ensure_group(conn, group_id)
        broadcast_repo.create(
            conn, task_id, payload.title.strip(), payload.message,
            payload.interval_seconds, payload.group_cooldown_seconds, enabled_ids,
            payload.loop_total, payload.loop_interval_seconds,
        )
    return {
        "id": task_id,
        "status": "queued",
        "total_count": len(enabled_ids),
        "skipped": skipped,
        "loop_total": payload.loop_total,
        "revision": bump_config_revision(),
    }


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


@router.put("/{task_id}")
def update_broadcast_intervals(
    task_id: str, payload: BroadcastIntervalsPayload
) -> dict[str, Any]:
    """Retune a task's pacing.

    The round gap is accepted at any time; the group delay is not, because it
    re-spaces sends that are already queued.
    """
    if payload.interval_seconds is None and payload.loop_interval_seconds is None:
        raise HTTPException(status_code=422, detail="没有需要修改的间隔")
    with connection() as conn:
        task = broadcast_repo.intervals(conn, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        if payload.interval_seconds is not None and task["status"] != "paused":
            raise HTTPException(status_code=409, detail="群间延时会影响已排定的队列，请先暂停任务")
        broadcast_repo.update_intervals(
            conn, task_id, payload.interval_seconds, payload.loop_interval_seconds
        )
    return {
        "saved": True,
        "interval_seconds": (
            payload.interval_seconds
            if payload.interval_seconds is not None
            else task["interval_seconds"]
        ),
        "loop_interval_seconds": (
            payload.loop_interval_seconds
            if payload.loop_interval_seconds is not None
            else task["loop_interval_seconds"]
        ),
        "revision": bump_config_revision(),
    }