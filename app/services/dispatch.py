"""Background scheduler draining the notification and broadcast queues.

A single worker coroutine performs every send serially. All QQ traffic
(private alerts and group broadcasts) shares one AIMD token bucket so a noon
burst cannot trip account risk control:

- the rate starts at 0.5 sends/s and grows +0.1 per 50 consecutive
  successes, capped at 1.0/s;
- any failed QQ send (exception or an empty NapCat ``message_id``) halves the
  rate, floor 0.1/s, and pauses QQ sending for 60 seconds;
- priority-0 alert jobs (现在/急) cost one token, everything else needs two
  tokens in the bucket, so one token always stays reserved for urgent alerts.

Alert jobs carry an expiry (5 min P0 / 15 min P1). Jobs that expire unsent are
dropped and their orders return to the undelivered state, so the next repost
of the same order re-enqueues a notification automatically. Orders are marked
delivered at enqueue time (see ``nonebot_bot``) so bursts cannot double-enqueue
while jobs wait in the queue; the worker only re-arms ``orders.sent_at`` after
a failure/expiry had cleared it.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import nonebot
from nonebot.adapters.onebot.v11 import Bot

from app.db import connection
from app.services.email import send_smtp_email
from app.settings import get_settings


GROUP_SYNC_INTERVAL_SECONDS = 300.0
SWEEP_INTERVAL_SECONDS = 3600.0
ORDERS_RETENTION_SECONDS = 7 * 86400
CIRCUIT_BREAK_SECONDS = 60.0


@dataclass
class AimdBucket:
    """Account-level QQ send pacing: token bucket with AIMD rate control."""

    rate: float = 0.5
    tokens: float = 3.0
    capacity: float = 3.0
    min_rate: float = 0.1
    max_rate: float = 1.0
    success_streak: int = 0
    paused_until: float = 0.0
    last_refill: float = 0.0

    def _refill(self, now: float) -> None:
        if self.last_refill:
            self.tokens = min(
                self.capacity, self.tokens + self.rate * (now - self.last_refill)
            )
        self.last_refill = now

    def try_acquire(self, now: float, priority: int = 1) -> bool:
        self._refill(now)
        if now < self.paused_until:
            return False
        needed = 1.0 if priority == 0 else 2.0
        if self.tokens < needed:
            return False
        self.tokens -= 1.0
        return True

    def on_success(self) -> None:
        self.success_streak += 1
        if self.success_streak >= 50:
            self.rate = min(self.max_rate, self.rate + 0.1)
            self.success_streak = 0

    def on_failure(self, now: float) -> None:
        self.rate = max(self.min_rate, self.rate / 2)
        self.success_streak = 0
        self.paused_until = now + CIRCUIT_BREAK_SECONDS


_bucket = AimdBucket()
_group_sync_at: float = 0.0
_sweep_at: float = 0.0
_stop_event = asyncio.Event()
_task: asyncio.Task | None = None


def _now() -> float:
    return time.monotonic()


def _iso_now() -> str:
    """UTC timestamp in the same ISO format the handler writes to expires_at,
    so lexicographic comparison in SQLite stays valid."""
    return datetime.now(timezone.utc).isoformat()


def _bot() -> Bot | None:
    bots = nonebot.get_bots()
    return next(iter(bots.values()), None)


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


# ---------------------------------------------------------------------------
# order delivery state reconciliation
# ---------------------------------------------------------------------------


def _fps(order_fp: object) -> list[str]:
    return [fp for fp in str(order_fp or "").split(",") if fp]


def _rearm_orders(conn: sqlite3.Connection, order_fp: object) -> None:
    """Send succeeded: restore the delivered state if a sibling failure or
    expiry had cleared it. ``n_push`` is counted once at enqueue time, not per
    destination, so it is not touched here."""
    for fp in _fps(order_fp):
        conn.execute(
            "UPDATE orders SET sent_at=? WHERE fp=? AND sent_at IS NULL",
            (time.time(), fp),
        )


def _release_orders(conn: sqlite3.Connection, order_fp: object) -> None:
    """A job died unsent: return its orders to the undelivered state so the
    next repost re-enqueues, unless another destination already delivered."""
    for fp in _fps(order_fp):
        conn.execute(
            "UPDATE orders SET sent_at=NULL WHERE fp=? AND NOT EXISTS ("
            "SELECT 1 FROM notification_jobs WHERE status='sent' "
            "AND instr(',' || order_fp || ',', ',' || ? || ',') > 0)",
            (fp, fp),
        )


def _finalize_hit(conn: sqlite3.Connection, hit_id: int) -> None:
    """Once no job for the hit is still in flight, fold job outcomes back into
    ``keyword_hits.notify_status``."""
    open_jobs = conn.execute(
        "SELECT COUNT(*) AS count FROM notification_jobs "
        "WHERE hit_id=? AND status IN ('pending', 'sending')",
        (hit_id,),
    ).fetchone()["count"]
    if open_jobs:
        return
    sent = conn.execute(
        "SELECT COUNT(*) AS count FROM notification_jobs "
        "WHERE hit_id=? AND status='sent'",
        (hit_id,),
    ).fetchone()["count"]
    conn.execute(
        "UPDATE keyword_hits SET notify_status=? "
        "WHERE id=? AND notify_status IN ('pending', 'queued')",
        ("sent" if sent else "expired", hit_id),
    )


# ---------------------------------------------------------------------------
# notification jobs (keyword alerts)
# ---------------------------------------------------------------------------


def _expire_jobs() -> None:
    """Drop pending jobs whose expiry has passed; their orders go back to the
    undelivered state so a repost re-enqueues them."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, hit_id, order_fp FROM notification_jobs "
            "WHERE status='pending' AND expires_at IS NOT NULL AND expires_at <= ?",
            (_iso_now(),),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE notification_jobs SET status='expired', last_error='expired before send' WHERE id=?",
                (row["id"],),
            )
            _release_orders(conn, row["order_fp"])
            _finalize_hit(conn, int(row["hit_id"]))


def _peek_notification() -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute(
            "SELECT j.id, j.hit_id, j.priority, j.expires_at, j.order_fp, "
            "d.kind, d.address, h.sender_name, h.sender_id, "
            "h.keyword_text_snapshot, h.message_text "
            "FROM notification_jobs j "
            "JOIN notification_destinations d ON d.id=j.destination_id "
            "JOIN keyword_hits h ON h.id=j.hit_id "
            "WHERE j.status='pending' AND j.next_attempt_at <= CURRENT_TIMESTAMP "
            "AND (j.expires_at IS NULL OR j.expires_at > ?) "
            "ORDER BY j.priority, j.id LIMIT 1",
            (_iso_now(),),
        ).fetchone()


def _claim_notification(job_id: int) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE notification_jobs SET status='sending', attempts=attempts+1 WHERE id=?",
            (job_id,),
        )


def _sent_notification(job: sqlite3.Row) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE notification_jobs SET status='sent', sent_at=CURRENT_TIMESTAMP WHERE id=?",
            (job["id"],),
        )
        _rearm_orders(conn, job["order_fp"])
        _finalize_hit(conn, int(job["hit_id"]))


def _fail_notification(job: sqlite3.Row, error: str) -> None:
    """Retry while the job still has lifetime left; past expiry, drop it so a
    fresh repost of the same order can re-enqueue."""
    expired = bool(job["expires_at"]) and str(job["expires_at"]) <= _iso_now()
    with connection() as conn:
        if expired:
            conn.execute(
                "UPDATE notification_jobs SET status='expired', last_error=? WHERE id=?",
                (error[:500], job["id"]),
            )
            _release_orders(conn, job["order_fp"])
            _finalize_hit(conn, int(job["hit_id"]))
        else:
            conn.execute(
                "UPDATE notification_jobs SET status='pending', last_error=?, "
                "next_attempt_at=datetime('now', '+60 seconds') WHERE id=?",
                (error[:500], job["id"]),
            )


async def _deliver_notification(bot: Bot, job: sqlite3.Row) -> None:
    text = (
        f"发送者：{job['sender_name']}（{job['sender_id']}）\n"
        f"关键词：{job['keyword_text_snapshot']}\n"
        f"消息内容：{job['message_text']}"
    )
    try:
        if job["kind"] == "qq":
            result = await bot.call_api(
                "send_private_msg",
                user_id=int(job["address"]),
                message=[{"type": "text", "data": {"text": text}}],
            )
            message_id = (
                str(result.get("message_id", "")) if isinstance(result, dict) else ""
            )
            if not message_id:
                # NapCat swallows risk-controlled sends into an empty id.
                raise RuntimeError("napcat returned empty message_id")
            _bucket.on_success()
        else:
            await send_smtp_email(
                get_settings(),
                job["address"],
                f"关键词命中：{job['keyword_text_snapshot']}",
                text,
            )
    except Exception as exc:
        if job["kind"] == "qq":
            _bucket.on_failure(_now())
            nonebot.logger.warning(
                "qq alert send failed; rate=%.2f/s, pausing %ds: %s",
                _bucket.rate,
                int(CIRCUIT_BREAK_SECONDS),
                exc,
            )
        _fail_notification(job, str(exc))
    else:
        _sent_notification(job)


# ---------------------------------------------------------------------------
# broadcast tasks
# ---------------------------------------------------------------------------


def _peek_broadcast() -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute(
            "SELECT g.task_id, g.group_id, t.message_json "
            "FROM broadcast_task_groups g JOIN broadcast_tasks t ON t.id=g.task_id "
            "WHERE g.status='queued' AND g.scheduled_at <= ? "
            "AND t.status IN ('queued','running') "
            "ORDER BY g.scheduled_at LIMIT 1",
            (_iso_now(),),
        ).fetchone()


def _claim_broadcast(row: sqlite3.Row) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE broadcast_task_groups SET status='sending', attempts=attempts+1 "
            "WHERE task_id=? AND group_id=?",
            (row["task_id"], row["group_id"]),
        )
        conn.execute(
            "UPDATE broadcast_tasks SET status='running', "
            "started_at=COALESCE(started_at, CURRENT_TIMESTAMP) WHERE id=?",
            (row["task_id"],),
        )


def _finish_broadcast(
    row: sqlite3.Row, message_id: str | None, error: str | None
) -> None:
    with connection() as conn:
        if error is None:
            conn.execute(
                "UPDATE broadcast_task_groups SET status='sent', sent_at=CURRENT_TIMESTAMP, message_id=? "
                "WHERE task_id=? AND group_id=?",
                (message_id, row["task_id"], row["group_id"]),
            )
            conn.execute(
                "UPDATE broadcast_tasks SET sent_count=sent_count+1 WHERE id=?",
                (row["task_id"],),
            )
        else:
            conn.execute(
                "UPDATE broadcast_task_groups SET status='failed', error_text=? "
                "WHERE task_id=? AND group_id=?",
                (error[:500], row["task_id"], row["group_id"]),
            )
            conn.execute(
                "UPDATE broadcast_tasks SET failed_count=failed_count+1 WHERE id=?",
                (row["task_id"],),
            )
        # Anything not terminal still counts as outstanding, including groups a
        # pause moved to 'paused'. Counting only queued/sending would finalise a
        # task that was just paused with work left.
        remaining = conn.execute(
            "SELECT COUNT(*) AS count FROM broadcast_task_groups "
            "WHERE task_id=? AND status NOT IN ('sent', 'failed', 'cancelled')",
            (row["task_id"],),
        ).fetchone()["count"]
        if remaining == 0:
            conn.execute(
                "UPDATE broadcast_tasks SET status=CASE WHEN failed_count > 0 "
                "THEN 'completed_with_errors' ELSE 'completed' END, "
                "finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["task_id"],),
            )


async def _deliver_broadcast(bot: Bot, row: sqlite3.Row) -> None:
    try:
        result = await bot.call_api(
            "send_group_msg",
            group_id=int(row["group_id"]),
            message=json.loads(row["message_json"]),
        )
    except Exception as exc:
        # Usually group-specific (bot muted/kicked), so it does not feed the
        # account-level AIMD bucket.
        _finish_broadcast(row, None, str(exc))
        return
    message_id = str(result.get("message_id", "")) if isinstance(result, dict) else ""
    if not message_id:
        # Empty id = NapCat swallowed the send (account risk control).
        _bucket.on_failure(_now())
        _finish_broadcast(row, None, "napcat returned empty message_id")
        return
    _bucket.on_success()
    _finish_broadcast(row, message_id, None)


# ---------------------------------------------------------------------------
# worker loop
# ---------------------------------------------------------------------------


async def _work_once(bot: Bot) -> str:
    """One scheduler step. Returns 'worked', 'throttled' or 'idle' so the loop
    can pick its sleep."""
    _expire_jobs()
    job = _peek_notification()
    if job is not None:
        if job["kind"] == "qq" and not _bucket.try_acquire(
            _now(), int(job["priority"])
        ):
            return "throttled"
        _claim_notification(int(job["id"]))
        await _deliver_notification(bot, job)
        return "worked"
    row = _peek_broadcast()
    if row is not None:
        if not _bucket.try_acquire(_now(), 1):
            return "throttled"
        _claim_broadcast(row)
        await _deliver_broadcast(bot, row)
        return "worked"
    return "idle"


def _sweep() -> None:
    """Hourly housekeeping: drop order rows far beyond the dedup window and
    requeue jobs a crash left behind in 'sending'."""
    with connection() as conn:
        conn.execute(
            "DELETE FROM orders WHERE last_seen < ?",
            (time.time() - ORDERS_RETENTION_SECONDS,),
        )
        conn.execute(
            "UPDATE notification_jobs SET status='pending' WHERE status='sending'"
        )


async def dispatch_loop() -> None:
    global _group_sync_at, _sweep_at
    while not _stop_event.is_set():
        bot = _bot()
        if bot is None:
            delay = 1.0
        else:
            now = _now()
            if now - _group_sync_at >= GROUP_SYNC_INTERVAL_SECONDS:
                await sync_groups(bot)
                _group_sync_at = now
            if now - _sweep_at >= SWEEP_INTERVAL_SECONDS:
                _sweep()
                _sweep_at = now
            outcome = await _work_once(bot)
            if outcome == "worked":
                continue
            delay = 0.3 if outcome == "throttled" else 1.0
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=delay)
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
