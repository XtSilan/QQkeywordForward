"""Data-access functions for broadcast tasks and their per-group schedule."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import row_dict


def list_tasks(conn, limit: int) -> list[dict[str, Any]]:
    # round_sent/round_failed only ever cover the round in flight: a round is
    # started by resetting every group row to 'queued' (see start_next_round),
    # while the task-level counters keep the cumulative totals.
    rows = conn.execute(
        "SELECT t.id, t.title, t.interval_seconds, t.group_cooldown_seconds, t.status, t.total_count, "
        "t.sent_count, t.failed_count, t.created_at, t.started_at, t.finished_at, "
        "t.loop_total, t.loop_current, t.loop_interval_seconds, "
        "(SELECT COUNT(*) FROM broadcast_task_groups g WHERE g.task_id=t.id AND g.status='sent') AS round_sent, "
        "(SELECT COUNT(*) FROM broadcast_task_groups g WHERE g.task_id=t.id AND g.status='failed') AS round_failed "
        "FROM broadcast_tasks t ORDER BY t.created_at DESC LIMIT ?",
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
    result["round_sent"] = sum(1 for group in groups if group["status"] == "sent")
    result["round_failed"] = sum(1 for group in groups if group["status"] == "failed")
    return result


def create(conn, task_id: str, title: str, message: list[dict[str, Any]],
           interval_seconds: int, group_cooldown_seconds: int, group_ids: list[str],
           loop_total: int, loop_interval_seconds: int) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO broadcast_tasks(id, title, message_json, interval_seconds, group_cooldown_seconds, "
        "status, total_count, created_at, loop_total, loop_current, loop_interval_seconds) "
        "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
        (task_id, title, json.dumps(message, ensure_ascii=False), interval_seconds,
         group_cooldown_seconds, len(group_ids), now.isoformat(),
         loop_total, 1 if loop_total > 0 else 0, loop_interval_seconds),
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
    conn.execute("UPDATE broadcast_tasks SET status='running', interval_seconds=? WHERE id=?", (interval_seconds, task_id))
    # Re-schedule remaining groups from now so a long pause doesn't trigger a
    # catch-up burst, and so a delay changed while paused takes effect at once.
    queued = conn.execute(
        "SELECT group_id FROM broadcast_task_groups WHERE task_id=? AND status='paused' ORDER BY scheduled_at",
        (task_id,),
    ).fetchall()
    for index, row in enumerate(queued):
        conn.execute(
            "UPDATE broadcast_task_groups SET status='queued', scheduled_at=? WHERE task_id=? AND group_id=?",
            ((now + timedelta(seconds=index * interval_seconds)).isoformat(), task_id, row["group_id"]),
        )


def intervals(conn, task_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT status, interval_seconds, loop_total, loop_current, loop_interval_seconds "
        "FROM broadcast_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    return row_dict(row) if row else None


def update_intervals(conn, task_id: str, interval_seconds: int | None,
                     loop_interval_seconds: int | None) -> None:
    if interval_seconds is not None:
        conn.execute(
            "UPDATE broadcast_tasks SET interval_seconds=? WHERE id=?", (interval_seconds, task_id)
        )
    if loop_interval_seconds is not None:
        conn.execute(
            "UPDATE broadcast_tasks SET loop_interval_seconds=? WHERE id=?",
            (loop_interval_seconds, task_id),
        )


def start_next_round(conn, task_id: str, interval_seconds: int, loop_interval_seconds: int) -> None:
    """Queue the next round of an auto-looping task.

    Every group row is reset and re-scheduled, so the per-group detail of the
    finished round is overwritten — the loop is there for the live "round X of Y"
    progress, and ``broadcast_tasks.sent_count``/``failed_count`` keep the
    cumulative totals. Rows are re-queued in their original order (``rowid``),
    which keeps each round's pacing identical to the schedule the operator saw.
    """
    conn.execute(
        "UPDATE broadcast_tasks SET loop_current=loop_current+1, status='running' WHERE id=?",
        (task_id,),
    )
    groups = conn.execute(
        "SELECT group_id FROM broadcast_task_groups WHERE task_id=? ORDER BY rowid", (task_id,)
    ).fetchall()
    start = datetime.now(timezone.utc) + timedelta(seconds=loop_interval_seconds)
    for index, row in enumerate(groups):
        conn.execute(
            "UPDATE broadcast_task_groups SET status='queued', scheduled_at=?, attempts=0, "
            "sent_at=NULL, message_id=NULL, error_text=NULL WHERE task_id=? AND group_id=?",
            ((start + timedelta(seconds=index * interval_seconds)).isoformat(), task_id, row["group_id"]),
        )