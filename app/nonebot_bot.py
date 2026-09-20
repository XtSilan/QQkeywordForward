import asyncio
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone

import nonebot
from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message
from nonebot.rule import to_me

from app.db import connection, init_db
from app.services import dispatch
from app.settings import get_settings


_cooldown_cleanup_at: float = 0


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


if __name__ == "__main__":
    run()
