"""Background scheduler draining the notification and broadcast queues.

Extracted from ``nonebot_bot`` so the runtime module only owns NoneBot wiring.
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone

import nonebot
from nonebot.adapters.onebot.v11 import Bot

from app.db import connection
from app.services.email import send_smtp_email
from app.settings import get_settings


GROUP_SYNC_INTERVAL_SECONDS = 300.0
SEND_RATE_LIMIT_PER_MINUTE = 5

_send_times: deque[float] = deque()
_group_sync_at: float = 0.0
_stop_event = asyncio.Event()
_task: asyncio.Task | None = None


def _bot() -> Bot | None:
    bots = nonebot.get_bots()
    return next(iter(bots.values()), None)


async def _rate_limit() -> None:
    now = asyncio.get_running_loop().time()
    while _send_times and now - _send_times[0] >= 60:
        _send_times.popleft()
    if len(_send_times) >= SEND_RATE_LIMIT_PER_MINUTE:
        await asyncio.sleep(max(0.1, 60 - (now - _send_times[0])))
        await _rate_limit()
    _send_times.append(asyncio.get_running_loop().time())


async def sync_groups(bot: Bot) -> None:
    try:
        groups = await bot.call_api("get_group_list")
    except Exception as exc:
        nonebot.logger.warning("group sync failed: %s", exc)
        return
    if not isinstance(groups, list):
        return
    with connection() as conn:
        for group in groups:
            group_id = str(group.get("group_id", "")).strip()
            if not group_id:
                continue
            name = str(group.get("group_name", ""))
            avatar = f"https://p.qlogo.cn/gh/{group_id}/{group_id}/100/"
            conn.execute(
                "INSERT INTO groups(group_id, name, avatar_url, last_synced_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(group_id) DO UPDATE SET name=excluded.name, avatar_url=excluded.avatar_url, last_synced_at=CURRENT_TIMESTAMP",
                (group_id, name, avatar),
            )


async def dispatch_notifications(bot: Bot) -> None:
    with connection() as conn:
        job = conn.execute(
            "SELECT j.id, j.hit_id, d.kind, d.address, "
            "h.sender_name, h.sender_id, "
            "h.keyword_text_snapshot, h.message_text "
            "FROM notification_jobs j JOIN notification_destinations d ON d.id=j.destination_id "
            "JOIN keyword_hits h ON h.id=j.hit_id WHERE j.status='pending' "
            "AND j.next_attempt_at <= CURRENT_TIMESTAMP ORDER BY j.id LIMIT 1"
        ).fetchone()
        if not job:
            return
        conn.execute("UPDATE notification_jobs SET status='sending', attempts=attempts+1 WHERE id=?", (job["id"],))
    message = [
        {"type": "text", "data": {"text": f"发送者：{job['sender_name']}（{job['sender_id']}）\n关键词：{job['keyword_text_snapshot']}\n消息内容：{job['message_text']}"}}
    ]
    try:
        if job["kind"] == "qq":
            await bot.call_api("send_private_msg", user_id=int(job["address"]), message=message)
        else:
            await send_smtp_email(
                get_settings(), job["address"],
                f"关键词命中：{job['keyword_text_snapshot']}",
                message[0]["data"]["text"],
            )
    except Exception as exc:
        with connection() as conn:
            conn.execute("UPDATE notification_jobs SET status='pending', last_error=?, next_attempt_at=datetime('now', '+60 seconds') WHERE id=?", (str(exc)[:500], job["id"]))
    else:
        with connection() as conn:
            conn.execute("UPDATE notification_jobs SET status='sent', sent_at=CURRENT_TIMESTAMP WHERE id=?", (job["id"],))
            pending = conn.execute(
                "SELECT COUNT(*) AS count FROM notification_jobs "
                "WHERE hit_id=? AND status!='sent'", (job["hit_id"],)
            ).fetchone()["count"]
            if pending == 0:
                conn.execute(
                    "UPDATE keyword_hits SET notify_status='sent' WHERE id=?", (job["hit_id"],)
                )


async def dispatch_broadcasts(bot: Bot) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        row = conn.execute(
            "SELECT g.task_id, g.group_id, t.message_json, t.status AS task_status "
            "FROM broadcast_task_groups g JOIN broadcast_tasks t ON t.id=g.task_id "
            "WHERE g.status='queued' AND g.scheduled_at <= ? AND t.status IN ('queued','running') "
            "ORDER BY g.scheduled_at LIMIT 1",
            (now,),
        ).fetchone()
        if not row:
            return
        conn.execute("UPDATE broadcast_task_groups SET status='sending', attempts=attempts+1 WHERE task_id=? AND group_id=?", (row["task_id"], row["group_id"]))
        conn.execute("UPDATE broadcast_tasks SET status='running', started_at=COALESCE(started_at, CURRENT_TIMESTAMP) WHERE id=?", (row["task_id"],))
    await _rate_limit()
    try:
        result = await bot.call_api("send_group_msg", group_id=int(row["group_id"]), message=json.loads(row["message_json"]))
    except Exception as exc:
        with connection() as conn:
            conn.execute("UPDATE broadcast_task_groups SET status='failed', error_text=? WHERE task_id=? AND group_id=?", (str(exc)[:500], row["task_id"], row["group_id"]))
            conn.execute("UPDATE broadcast_tasks SET failed_count=failed_count+1 WHERE id=?", (row["task_id"],))
    else:
        message_id = str(result.get("message_id", "")) if isinstance(result, dict) else ""
        with connection() as conn:
            conn.execute("UPDATE broadcast_task_groups SET status='sent', sent_at=CURRENT_TIMESTAMP, message_id=? WHERE task_id=? AND group_id=?", (message_id, row["task_id"], row["group_id"]))
            conn.execute("UPDATE broadcast_tasks SET sent_count=sent_count+1 WHERE id=?", (row["task_id"],))
    with connection() as conn:
        remaining = conn.execute("SELECT COUNT(*) AS count FROM broadcast_task_groups WHERE task_id=? AND status IN ('queued','sending')", (row["task_id"],)).fetchone()["count"]
        if remaining == 0:
            conn.execute("UPDATE broadcast_tasks SET status=CASE WHEN failed_count > 0 THEN 'completed_with_errors' ELSE 'completed' END, finished_at=CURRENT_TIMESTAMP WHERE id=?", (row["task_id"],))


async def dispatch_loop() -> None:
    global _group_sync_at
    while not _stop_event.is_set():
        bot = _bot()
        if bot:
            now = asyncio.get_running_loop().time()
            if now - _group_sync_at >= GROUP_SYNC_INTERVAL_SECONDS:
                await sync_groups(bot)
                _group_sync_at = now
            await dispatch_notifications(bot)
            await dispatch_broadcasts(bot)
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


async def start() -> None:
    """Launch the scheduler loop (idempotent per process)."""
    global _task
    _stop_event.clear()
    _task = asyncio.create_task(dispatch_loop())


async def stop() -> None:
    """Signal the scheduler to finish and wait for it."""
    global _task
    _stop_event.set()
    if _task:
        await _task
        _task = None
