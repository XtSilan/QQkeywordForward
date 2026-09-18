import json
import re
from datetime import datetime, timezone

import nonebot
from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message
from nonebot.rule import to_me

from app.db import connection, init_db
from app.settings import get_settings


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
                conn.execute(
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
        nonebot.logger.info(
            "keyword_hit group_id=%s user_id=%s message_id=%s",
            event.group_id,
            event.user_id,
            event.message_id,
        )

    nonebot.run()


if __name__ == "__main__":
    run()
