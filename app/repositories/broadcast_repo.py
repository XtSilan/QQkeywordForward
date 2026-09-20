"""Data-access functions for broadcast tasks and their per-group schedule."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import row_dict


def list_tasks(conn, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, title, interval_seconds, group_cooldown_seconds, status, total_count, "
        "sent_count, failed_count, created_at, started_at, finished_at "
        "FROM broadcast_tasks ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [row_dict(row) for row in rows]


def get_task(conn, task_id: str) -> dict[str, Any] | None:
    task = conn.execute("SELECT * FROM broadcast_tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        return None
    groups = conn.execute(
        "SELECT task_id, group_id, status, scheduled_at, sent_at, message_id, error_code, error_text, attempts "
        "FROM broadcast_task_groups WHERE task_id=? ORDER BY scheduled_at",
        (task_id,),
    ).fetchall()
    result = row_dict(task)
    result["message"] = json.loads(result.pop("message_json"))
    result["groups"] = [row_dict(group) for group in groups]
    return result


def create(conn, task_id: str, title: str, message: list[dict[str, Any]],
           interval_seconds: int, group_cooldown_seconds: int, group_ids: list[str]) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO broadcast_tasks(id, title, message_json, interval_seconds, group_cooldown_seconds, "
        "status, total_count, created_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)",
        (task_id, title, json.dumps(message, ensure_ascii=False), interval_seconds,
         group_cooldown_seconds, len(group_ids), now.isoformat()),
    )
    for index, group_id in enumerate(group_ids):
        conn.execute(
            "INSERT INTO broadcast_task_groups(task_id, group_id, scheduled_at) VALUES (?, ?, ?)",
            (task_id, group_id, (now + timedelta(seconds=index * interval_seconds)).isoformat()),
        )


def cancel(conn, task_id: str) -> bool:
    cursor = conn.execute(
        "UPDATE broadcast_tasks SET status='cancelled', cancelled_at=CURRENT_TIMESTAMP "
        "WHERE id=? AND status IN ('draft', 'queued', 'running', 'paused')",
        (task_id,),
    )
    if cursor.rowcount == 0:
        return False
    conn.execute(
        "UPDATE broadcast_task_groups SET status='cancelled' WHERE task_id=? AND status IN ('queued','paused')",
        (task_id,),
    )
    return True


def pause(conn, task_id: str) -> bool:
    cursor = conn.execute(
        "UPDATE broadcast_tasks SET status='paused' "
        "WHERE id=? AND status IN ('queued', 'running')",
        (task_id,),
    )
    if cursor.rowcount == 0:
        return False
    conn.execute(
        "UPDATE broadcast_task_groups SET status='paused' WHERE task_id=? AND status='queued'",
        (task_id,),
    )
    return True


def paused_interval(conn, task_id: str) -> int | None:
    row = conn.execute(
        "SELECT interval_seconds FROM broadcast_tasks WHERE id=? AND status='paused'",
        (task_id,),
    ).fetchone()
    return int(row["interval_seconds"]) if row else None


def resume(conn, task_id: str, interval_seconds: int) -> None:
    now = datetime.now(timezone.utc)
    conn.execute("UPDATE broadcast_tasks SET status='running' WHERE id=?", (task_id,))
    # Re-schedule remaining groups from now so a long pause doesn't trigger a
    # catch-up burst.
    queued = conn.execute(
        "SELECT group_id FROM broadcast_task_groups WHERE task_id=? AND status='paused' ORDER BY scheduled_at",
        (task_id,),
    ).fetchall()
    for index, row in enumerate(queued):
        conn.execute(
            "UPDATE broadcast_task_groups SET status='queued', scheduled_at=? WHERE task_id=? AND group_id=?",
            ((now + timedelta(seconds=index * interval_seconds)).isoformat(), task_id, row["group_id"]),
        )


def task_status(conn, task_id: str) -> str | None:
    row = conn.execute("SELECT status FROM broadcast_tasks WHERE id=?", (task_id,)).fetchone()
    return str(row["status"]) if row else None


def reschedule_queued(conn, task_id: str, interval_seconds: int) -> None:
    """Re-space queued groups under a new interval so the change shows at once."""
    now = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE broadcast_tasks SET interval_seconds=? WHERE id=?",
        (interval_seconds, task_id),
    )
    queued = conn.execute(
        "SELECT group_id FROM broadcast_task_groups WHERE task_id=? AND status='queued' ORDER BY scheduled_at",
        (task_id,),
    ).fetchall()
    for index, row in enumerate(queued):
        conn.execute(
            "UPDATE broadcast_task_groups SET scheduled_at=? WHERE task_id=? AND group_id=?",
            ((now + timedelta(seconds=index * interval_seconds)).isoformat(), task_id, row["group_id"]),
        )