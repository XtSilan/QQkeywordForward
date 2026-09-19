import asyncio
import hashlib
import json
import re
import smtplib
import unicodedata
from email.message import EmailMessage
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
_group_sync_at: float = 0
_cooldown_cleanup_at: float = 0


def _smtp_send(settings, recipient: str, subject: str, body: str) -> None:
    config = _smtp_config(settings)
    if not config["host"] or not config["from_address"]:
        raise RuntimeError("SMTP_HOST 和 SMTP_FROM 未配置")
    message = EmailMessage()
    message["From"] = config["from_address"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    smtp_class = smtplib.SMTP_SSL if config["ssl"] else smtplib.SMTP
    with smtp_class(config["host"], config["port"], timeout=config["timeout"]) as server:
        server.ehlo()
        if config["starttls"] and not config["ssl"]:
            server.starttls()
            server.ehlo()
        if config["username"]:
            server.login(config["username"], config["password"])
        server.send_message(message)


def _smtp_config(settings) -> dict[str, object]:
    values = {
        "host": settings.smtp_host, "port": settings.smtp_port, "username": settings.smtp_username,
        "password": settings.smtp_password, "from_address": settings.smtp_from,
        "starttls": settings.smtp_starttls, "ssl": settings.smtp_ssl, "timeout": settings.smtp_timeout,
    }
    try:
        with connection() as conn:
            rows = conn.execute("SELECT key, value FROM app_meta WHERE key LIKE 'smtp_%'").fetchall()
        mapping = {row["key"]: row["value"] for row in rows}
        for key, value in mapping.items():
            short = key.removeprefix("smtp_")
            if short in values:
                if short in {"port", "timeout"}:
                    values[short] = int(value)
                elif short in {"starttls", "ssl"}:
                    values[short] = value.lower() == "true"
                elif short == "from":
                    values["from_address"] = value
                else:
                    values[short] = value
    except Exception:
        pass
    return values


async def send_smtp_email(settings, recipient: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_smtp_send, settings, recipient, subject, body)


def message_text(message: Message) -> str:
    return "".join(segment.data.get("text", "") for segment in message if segment.type == "text")


def message_segments(message: Message) -> list[dict[str, object]]:
    """Serialize OneBot message segments without relying on adapter-specific helpers."""
    return [{"type": segment.type, "data": dict(segment.data)} for segment in message]


def _duplicate_cooling_settings(conn) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT key, value FROM app_meta WHERE key IN "
        "('duplicate_message_threshold', 'duplicate_message_cooldown_seconds')"
    ).fetchall()
    values = {str(row["key"]): str(row["value"]) for row in rows}
    try:
        threshold = max(2, int(values.get("duplicate_message_threshold", "2")))
        cooldown_seconds = max(
            60, int(values.get("duplicate_message_cooldown_seconds", "600"))
        )
    except ValueError:
        return 2, 600
    return threshold, cooldown_seconds


def _should_suppress_duplicate(
    conn, text: str, threshold: int, cooldown_seconds: int, now: float
) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(
        character
        for character in normalized
        if not character.isspace() and unicodedata.category(character) != "Cf"
    )
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    state = conn.execute(
        "SELECT occurrence_count, last_seen_at, cooldown_until "
        "FROM keyword_message_cooldowns WHERE message_fingerprint=?",
        (fingerprint,),
    ).fetchone()
    if not state:
        conn.execute(
            "INSERT INTO keyword_message_cooldowns(message_fingerprint, occurrence_count, last_seen_at) "
            "VALUES (?, 1, ?)",
            (fingerprint, now),
        )
        return False

    cooldown_until = float(state["cooldown_until"] or 0)
    if cooldown_until > now:
        conn.execute(
            "UPDATE keyword_message_cooldowns SET last_seen_at=? "
            "WHERE message_fingerprint=?",
            (now, fingerprint),
        )
        return True

    last_seen_at = float(state["last_seen_at"])
    if cooldown_until or now - last_seen_at >= cooldown_seconds:
        conn.execute(
            "UPDATE keyword_message_cooldowns SET occurrence_count=1, last_seen_at=?, cooldown_until=NULL "
            "WHERE message_fingerprint=?",
            (now, fingerprint),
        )
        return False

    occurrence_count = int(state["occurrence_count"]) + 1
    enters_cooldown = occurrence_count >= threshold
    conn.execute(
        "UPDATE keyword_message_cooldowns SET occurrence_count=?, last_seen_at=?, cooldown_until=? "
        "WHERE message_fingerprint=?",
        (
            occurrence_count,
            now,
            now + cooldown_seconds if enters_cooldown else None,
            fingerprint,
        ),
    )
    return enters_cooldown


def _prune_duplicate_state(conn, now: float, cooldown_seconds: int) -> None:
    global _cooldown_cleanup_at
    if now - _cooldown_cleanup_at < 300:
        return
    conn.execute(
        "DELETE FROM keyword_message_cooldowns WHERE last_seen_at < ?",
        (now - cooldown_seconds,),
    )
    conn.execute(
        "DELETE FROM sender_message_cooldowns WHERE cooldown_until <= ?", (now,)
    )
    _cooldown_cleanup_at = now


def _sender_is_cooling(conn, sender_id: str, now: float) -> bool:
    row = conn.execute(
        "SELECT cooldown_until FROM sender_message_cooldowns WHERE sender_id=?",
        (sender_id,),
    ).fetchone()
    if not row:
        return False
    if float(row["cooldown_until"]) > now:
        return True
    conn.execute("DELETE FROM sender_message_cooldowns WHERE sender_id=?", (sender_id,))
    return False


def _cooldown_sender(
    conn, sender_id: str, now: float, cooldown_seconds: int
) -> None:
    conn.execute(
        "INSERT INTO sender_message_cooldowns(sender_id, triggered_at, cooldown_until) "
        "VALUES (?, ?, ?) ON CONFLICT(sender_id) DO UPDATE SET "
        "triggered_at=excluded.triggered_at, cooldown_until=excluded.cooldown_until",
        (sender_id, now, now + cooldown_seconds),
    )


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
            duplicate_threshold, duplicate_cooldown_seconds = _duplicate_cooling_settings(conn)
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
            matched_rows = [
                row
                for row in rows
                if re.search(
                    row["pattern"], text, flags if row["ignore_case"] else 0
                )
                is not None
            ]
            if not matched_rows:
                return
            matched_keywords = list(
                dict.fromkeys(str(row["display_text"]) for row in matched_rows)
            )
            now = datetime.now(timezone.utc)
            _prune_duplicate_state(
                conn, now.timestamp(), duplicate_cooldown_seconds
            )
            sender_id = str(event.user_id)
            if _sender_is_cooling(conn, sender_id, now.timestamp()):
                nonebot.logger.info(
                    "sender_cooldown_suppressed group_id=%s user_id=%s message_id=%s",
                    event.group_id,
                    event.user_id,
                    event.message_id,
                )
                return
            if _should_suppress_duplicate(
                conn,
                text,
                duplicate_threshold,
                duplicate_cooldown_seconds,
                now.timestamp(),
            ):
                _cooldown_sender(
                    conn,
                    sender_id,
                    now.timestamp(),
                    duplicate_cooldown_seconds,
                )
                nonebot.logger.info(
                    "duplicate_message_suppressed group_id=%s user_id=%s message_id=%s",
                    event.group_id,
                    event.user_id,
                    event.message_id,
                )
                return
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
                    matched_rows[0]["name"],
                    sender_id,
                    event.sender.card or event.sender.nickname or "",
                    matched_rows[0]["id"],
                    "、".join(matched_keywords),
                    json.dumps(message_segments(event.get_message()), ensure_ascii=False),
                    text,
                    str(event.message_id),
                    now.isoformat(),
                ),
            )
            hit_id = int(cursor.lastrowid)
            destination_ids: set[int] = set()
            for row in matched_rows:
                destinations = conn.execute(
                    "SELECT DISTINCT d.id FROM notification_destinations d "
                    "WHERE d.enabled=1 AND ("
                    "EXISTS (SELECT 1 FROM keyword_notification_bindings kb "
                    "WHERE kb.keyword_id=? AND kb.destination_id=d.id AND kb.enabled=1) "
                    "OR (NOT EXISTS (SELECT 1 FROM keyword_notification_bindings kbx "
                    "WHERE kbx.keyword_id=?) AND EXISTS (SELECT 1 FROM notification_destination_bindings b "
                    "JOIN group_notification_settings s ON s.group_id=b.group_id "
                    "WHERE b.group_id=? AND b.destination_id=d.id "
                    "AND ((d.kind='qq' AND s.qq_enabled=1) OR (d.kind='email' AND s.email_enabled=1))))"
                    ")",
                    (row["id"], row["id"], str(event.group_id)),
                ).fetchall()
                destination_ids.update(int(item["id"]) for item in destinations)
            for destination_id in destination_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO notification_jobs(hit_id, destination_id) VALUES (?, ?)",
                    (hit_id, destination_id),
                )
            conn.execute(
                "UPDATE keyword_hits SET notify_status=? WHERE id=?",
                ("queued" if destination_ids else "no_destination", hit_id),
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


async def _sync_groups(bot: Bot) -> None:
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


async def _dispatch_notifications(bot: Bot) -> None:
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
    global _group_sync_at
    while not _stop_scheduler.is_set():
        bot = _bot()
        if bot:
            now = asyncio.get_running_loop().time()
            if now - _group_sync_at >= 300:
                await _sync_groups(bot)
                _group_sync_at = now
            await _dispatch_notifications(bot)
            await _dispatch_broadcasts(bot)
        try:
            await asyncio.wait_for(_stop_scheduler.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    run()
