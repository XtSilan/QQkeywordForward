import json
import re
import asyncio
from collections import deque
from datetime import datetime, timezone

import nonebot
from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message
from nonebot.rule import to_me

from app.db import connection, init_db
from app.settings import get_settings


_scheduler_task: asyncio.Task | None = None
_stop_scheduler = asyncio.Event()
_send_times: deque[float] = deque()


def message_text(message: Message) -> str:
    return "".join(segment.data.get("text", "") for segment in message if segment.type == "text")


def run() -> None:
    settings = get_settings()
    init_db()
    nonebot.init(
        _env=settings.environment,
        driver=settings.driver,
        host="0.0.0.0",
        port=8081,
    )
    driver = nonebot.get_driver()
    driver.register_adapter(Adapter)

    @driver.on_startup
    async def start_scheduler() -> None:
        global _scheduler_task
        _stop_scheduler.clear()
        _scheduler_task = asyncio.create_task(dispatch_loop())

    @driver.on_shutdown
    async def stop_scheduler() -> None:
        _stop_scheduler.set()
        if _scheduler_task:
            await _scheduler_task

    matcher = nonebot.on_message(priority=10, block=False)

    @matcher.handle()
    async def handle_message(bot: Bot, event: GroupMessageEvent) -> None:
        text = message_text(event.get_message())
        if not text:
            return
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.display_text, r.pattern, r.ignore_case,
                       b.cooldown_seconds, g.name
                FROM group_keyword_bindings b
                JOIN keyword_rules r ON r.id = b.keyword_id
                JOIN groups g ON g.group_id = b.group_id
                WHERE b.group_id = ? AND b.enabled = 1 AND r.deleted_at IS NULL
                """,
                (str(event.group_id),),
            ).fetchall()
            flags = re.IGNORECASE
            for row in rows:
                pattern = row["pattern"]
                if re.search(pattern, text, flags if row["ignore_case"] else 0) is None:
                    continue
                cursor = conn.execute(
                    """
                    INSERT INTO keyword_hits(
                      group_id, group_name, sender_id, sender_name, keyword_id,
                      keyword_text_snapshot, message_json, message_text,
                      message_id, hit_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.group_id),
                        row["name"],
                        str(event.user_id),
                        event.sender.card or event.sender.nickname or "",
                        row["id"],
                        row["display_text"],
                        json.dumps(event.get_message().export(), ensure_ascii=False),
                        text,
                        str(event.message_id),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                hit_id = int(cursor.lastrowid)
                destinations = conn.execute(
                    "SELECT d.id FROM notification_destinations d "
                    "JOIN notification_destination_bindings b ON b.destination_id=d.id "
                    "JOIN group_notification_settings s ON s.group_id=b.group_id "
                    "WHERE b.group_id=? AND d.enabled=1 AND ((d.kind='qq' AND s.qq_enabled=1) "
                    "OR (d.kind='email' AND s.email_enabled=1))",
                    (str(event.group_id),),
                ).fetchall()
                for destination in destinations:
                    conn.execute(
                        "INSERT OR IGNORE INTO notification_jobs(hit_id, destination_id) VALUES (?, ?)",
                        (hit_id, destination["id"]),
                    )
        nonebot.logger.info(
            "keyword_hit group_id=%s user_id=%s message_id=%s",
            event.group_id,
            event.user_id,
            event.message_id,
        )

    nonebot.run()


async def _rate_limit() -> None:
    now = asyncio.get_running_loop().time()
    while _send_times and now - _send_times[0] >= 60:
        _send_times.popleft()
    if len(_send_times) >= 5:
        await asyncio.sleep(max(0.1, 60 - (now - _send_times[0])))
        await _rate_limit()
    _send_times.append(asyncio.get_running_loop().time())


def _bot() -> Bot | None:
    bots = nonebot.get_bots()
    return next(iter(bots.values()), None)


async def _dispatch_notifications(bot: Bot) -> None:
    with connection() as conn:
        job = conn.execute(
            "SELECT j.id, j.hit_id, d.kind, d.address, h.group_name, h.group_id, h.sender_name, "
            "h.sender_id, h.keyword_text_snapshot, h.message_text, h.hit_at "
            "FROM notification_jobs j JOIN notification_destinations d ON d.id=j.destination_id "
            "JOIN keyword_hits h ON h.id=j.hit_id WHERE j.status='pending' "
            "AND j.next_attempt_at <= CURRENT_TIMESTAMP ORDER BY j.id LIMIT 1"
        ).fetchone()
        if not job:
            return
        conn.execute("UPDATE notification_jobs SET status='sending', attempts=attempts+1 WHERE id=?", (job["id"],))
    if job["kind"] != "qq":
        with connection() as conn:
            conn.execute("UPDATE notification_jobs SET status='failed', last_error=? WHERE id=?", ("email sender not configured", job["id"]))
        return
    message = [
        {"type": "text", "data": {"text": f"[关键词命中]\n群：{job['group_name']}（{job['group_id']}）\n发送者：{job['sender_name']}（{job['sender_id']}）\n命中：{job['keyword_text_snapshot']}\n时间：{job['hit_at']}\n消息：{job['message_text']}"}}
    ]
    try:
        await bot.call_api("send_private_msg", user_id=int(job["address"]), message=message)
    except Exception as exc:
        with connection() as conn:
            conn.execute("UPDATE notification_jobs SET status='pending', last_error=?, next_attempt_at=datetime('now', '+60 seconds') WHERE id=?", (str(exc)[:500], job["id"]))
    else:
        with connection() as conn:
            conn.execute("UPDATE notification_jobs SET status='sent', sent_at=CURRENT_TIMESTAMP WHERE id=?", (job["id"],))


async def _dispatch_broadcasts(bot: Bot) -> None:
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
    while not _stop_scheduler.is_set():
        bot = _bot()
        if bot:
            await _dispatch_notifications(bot)
            await _dispatch_broadcasts(bot)
        try:
            await asyncio.wait_for(_stop_scheduler.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    run()
