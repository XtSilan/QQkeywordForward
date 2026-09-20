import json
import re
from datetime import datetime, timedelta, timezone

import nonebot
from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message

from app.db import connection, init_db
from app.services import dispatch
from app.services import orders as order_dedup
from app.settings import get_settings


_msgs_cleanup_at: float = 0


def message_text(message: Message) -> str:
    return "".join(segment.data.get("text", "") for segment in message if segment.type == "text")


def message_segments(message: Message) -> list[dict[str, object]]:
    """Serialize OneBot message segments without relying on adapter-specific helpers."""
    return [{"type": segment.type, "data": dict(segment.data)} for segment in message]


def _prune_msgs(conn, now: float) -> None:
    """Bound the idempotency table; replays only matter for a short window."""
    global _msgs_cleanup_at
    if now - _msgs_cleanup_at < 300:
        return
    conn.execute("DELETE FROM msgs WHERE seen_at < ?", (now - 86400,))
    _msgs_cleanup_at = now


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
        await dispatch.start()

    @driver.on_shutdown
    async def stop_scheduler() -> None:
        await dispatch.stop()

    matcher = nonebot.on_message(priority=10, block=False)

    @matcher.handle()
    async def handle_message(bot: Bot, event: GroupMessageEvent) -> None:
        text = message_text(event.get_message())
        if not text:
            return
        with connection() as conn:
            now = datetime.now(timezone.utc)
            now_ts = now.timestamp()
            _prune_msgs(conn, now_ts)
            cursor = conn.execute(
                "INSERT OR IGNORE INTO msgs(gid, mid, seen_at) VALUES (?, ?, ?)",
                (str(event.group_id), str(event.message_id), now_ts),
            )
            if cursor.rowcount == 0:
                return  # NapCat reconnect replay of an already-seen message
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
            sender_id = str(event.user_id)
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

            dedup = order_dedup.load_settings(conn)
            push_fps: set[str] = set()
            if dedup.enabled:
                lexicon = [
                    str(r["display_text"])
                    for r in conn.execute(
                        "SELECT DISTINCT display_text FROM keyword_rules "
                        "WHERE deleted_at IS NULL"
                    ).fetchall()
                ]
                candidates = order_dedup.parse(text, lexicon, now_ts, dedup)
                for cand in candidates:
                    fp, action = order_dedup.decide(conn, cand, now_ts, dedup)
                    if action == "push":
                        push_fps.add(fp)
            should_push = bool(push_fps) or not dedup.enabled
            if should_push and destination_ids:
                priority = 0 if re.search("现在|急", text) else 1
                expires_at = (
                    now + timedelta(seconds=300 if priority == 0 else 900)
                ).isoformat()
                for destination_id in destination_ids:
                    conn.execute(
                        "INSERT OR IGNORE INTO notification_jobs(hit_id, destination_id, priority, expires_at) "
                        "VALUES (?, ?, ?, ?)",
                        (hit_id, destination_id, priority, expires_at),
                    )
                for fp in push_fps:
                    order_dedup.mark_sent(conn, fp, now_ts)
            if should_push:
                status = "queued" if destination_ids else "no_destination"
            else:
                status = "suppressed"
            conn.execute(
                "UPDATE keyword_hits SET notify_status=? WHERE id=?",
                (status, hit_id),
            )
            if not should_push:
                nonebot.logger.info(
                    "order_dedup_%s group_id=%s user_id=%s message_id=%s",
                    status,
                    event.group_id,
                    event.user_id,
                    event.message_id,
                )
        nonebot.logger.info(
            "keyword_hit group_id=%s user_id=%s message_id=%s",
            event.group_id,
            event.user_id,
            event.message_id,
        )

    nonebot.run()


if __name__ == "__main__":
    run()
