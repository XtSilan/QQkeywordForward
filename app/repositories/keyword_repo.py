"""Data-access functions for keywords. Pure SQL; no HTTP/business logic.

Functions take an open ``sqlite3.Connection`` so the API layer controls the
transaction boundary (multiple inserts must stay atomic).
"""
from __future__ import annotations

import re
from typing import Any

from app.db import row_dict


# -- read --------------------------------------------------------------------

def list_keywords(conn, group_id: str | None) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT r.id, r.display_text, r.match_mode, r.ignore_case, r.created_at, "
        "r.updated_at, r.sort_order, COUNT(DISTINCT b.group_id) AS group_count "
        "FROM keyword_rules r LEFT JOIN group_keyword_bindings b "
        "ON b.keyword_id = r.id AND b.enabled = 1 "
        "WHERE r.deleted_at IS NULL "
        "AND (? IS NULL OR EXISTS (SELECT 1 FROM group_keyword_bindings gb "
        "WHERE gb.keyword_id = r.id AND gb.group_id = ?)) "
        "GROUP BY r.id ORDER BY r.sort_order ASC, r.display_text COLLATE NOCASE ASC, r.id DESC",
        (group_id, group_id),
    ).fetchall()
    result = [row_dict(row) for row in rows]
    for item in result:
        bindings = conn.execute(
            "SELECT group_id, enabled, cooldown_seconds FROM group_keyword_bindings "
            "WHERE keyword_id = ? ORDER BY group_id",
            (item["id"],),
        ).fetchall()
        item["bindings"] = [row_dict(binding) for binding in bindings]
        destinations = conn.execute(
            "SELECT destination_id FROM keyword_notification_bindings "
            "WHERE keyword_id=? AND enabled=1 ORDER BY destination_id",
            (item["id"],),
        ).fetchall()
        item["destination_ids"] = [int(destination["destination_id"]) for destination in destinations]
    return result


def find_by_text(conn, display_text: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM keyword_rules WHERE display_text=? AND deleted_at IS NULL",
        (display_text,),
    ).fetchone()
    return int(row["id"]) if row else None


def get_by_id(conn, keyword_id: int) -> bool:
    return bool(
        conn.execute(
            "SELECT id FROM keyword_rules WHERE id=? AND deleted_at IS NULL", (keyword_id,)
        ).fetchone()
    )


def next_sort_order(conn) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM keyword_rules WHERE deleted_at IS NULL"
    ).fetchone()
    return int(row[0]) if row else 1


# -- write -------------------------------------------------------------------

def insert(conn, display_text: str, sort_order: int) -> int:
    cursor = conn.execute(
        "INSERT INTO keyword_rules(display_text, pattern, match_mode, ignore_case, sort_order, updated_at) "
        "VALUES (?, ?, 'literal_search', 1, ?, CURRENT_TIMESTAMP)",
        (display_text, re.escape(display_text), sort_order),
    )
    return int(cursor.lastrowid)


def create(conn, display_text: str, group_ids: list[str], enabled: bool, cooldown_seconds: int) -> int:
    keyword_id = insert(conn, display_text, next_sort_order(conn))
    bind_groups(conn, keyword_id, group_ids, enabled, cooldown_seconds)
    return keyword_id


def upsert_pattern(conn, display_text: str, keyword_id: int) -> None:
    conn.execute(
        "UPDATE keyword_rules SET pattern=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (re.escape(display_text), keyword_id),
    )


def bind_groups(conn, keyword_id: int, group_ids: list[str], enabled: bool, cooldown_seconds: int) -> None:
    for group_id in group_ids:
        conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
        conn.execute(
            "INSERT INTO group_keyword_bindings(group_id, keyword_id, enabled, cooldown_seconds) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(group_id, keyword_id) DO UPDATE SET "
            "enabled=excluded.enabled, cooldown_seconds=excluded.cooldown_seconds, updated_at=CURRENT_TIMESTAMP",
            (group_id, keyword_id, int(enabled), cooldown_seconds),
        )


def set_notifications(conn, keyword_id: int, destination_ids: list[int]) -> None:
    conn.execute("DELETE FROM keyword_notification_bindings WHERE keyword_id=?", (keyword_id,))
    for destination_id in destination_ids:
        conn.execute(
            "INSERT INTO keyword_notification_bindings(keyword_id, destination_id, enabled) VALUES (?, ?, 1)",
            (keyword_id, destination_id),
        )


def binding_groups(conn, keyword_id: int) -> list[str]:
    return [
        str(row["group_id"])
        for row in conn.execute(
            "SELECT group_id FROM group_keyword_bindings WHERE keyword_id=?", (keyword_id,)
        ).fetchall()
    ]


def soft_delete(conn, keyword_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE keyword_rules SET deleted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=? AND deleted_at IS NULL",
        (keyword_id,),
    )
    return cursor.rowcount > 0


def update_display(conn, keyword_id: int, display_text: str) -> None:
    """Update display text and pattern on the rule itself (keyword_rules)."""
    conn.execute(
        "UPDATE keyword_rules SET display_text=?, pattern=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=?",
        (display_text, re.escape(display_text), keyword_id),
    )


def update_bindings(conn, keyword_id: int, enabled: bool | None, cooldown_seconds: int | None) -> None:
    """Update enabled/cooldown on the binding rows (group_keyword_bindings)."""
    changes: list[str] = []
    values: list[Any] = []
    if enabled is not None:
        changes.append("enabled = ?")
        values.append(int(enabled))
    if cooldown_seconds is not None:
        changes.append("cooldown_seconds = ?")
        values.append(cooldown_seconds)
    conn.execute("UPDATE keyword_rules SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (keyword_id,))
    if changes:
        conn.execute(
            f"UPDATE group_keyword_bindings SET {', '.join(changes)}, updated_at=CURRENT_TIMESTAMP "
            "WHERE keyword_id = ?",
            (*values, keyword_id),
        )


def bulk_toggle(conn, keyword_ids: list[int], enabled: bool) -> int:
    placeholders = ",".join("?" for _ in keyword_ids)
    cursor = conn.execute(
        f"UPDATE group_keyword_bindings SET enabled=?, updated_at=CURRENT_TIMESTAMP "
        f"WHERE keyword_id IN ({placeholders})",
        (int(enabled), *keyword_ids),
    )
    touched = cursor.rowcount
    if touched == 0:
        conn.execute(
            f"UPDATE keyword_rules SET enabled=?, updated_at=CURRENT_TIMESTAMP "
            f"WHERE id IN ({placeholders})",
            (int(enabled), *keyword_ids),
        )
    conn.execute(
        f"UPDATE keyword_rules SET updated_at=CURRENT_TIMESTAMP "
        f"WHERE id IN ({placeholders})",
        tuple(keyword_ids),
    )
    return touched


def bulk_delete(conn, keyword_ids: list[int]) -> None:
    placeholders = ",".join("?" for _ in keyword_ids)
    conn.execute(
        f"UPDATE keyword_rules SET deleted_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
        tuple(keyword_ids),
    )


def reorder_alphabetical(conn) -> None:
    conn.execute(
        "UPDATE keyword_rules SET sort_order = (SELECT COUNT(*) FROM keyword_rules AS k "
        "WHERE k.deleted_at IS NULL AND (k.display_text COLLATE NOCASE "
        "< keyword_rules.display_text COLLATE NOCASE "
        "OR (k.display_text = keyword_rules.display_text AND k.id < keyword_rules.id)) ) + 1 "
        "WHERE deleted_at IS NULL"
    )


def reorder_manual(conn, keyword_ids: list[int]) -> None:
    for index, keyword_id in enumerate(keyword_ids, start=1):
        conn.execute(
            "UPDATE keyword_rules SET sort_order=? WHERE id=?", (index, keyword_id)
        )


def bulk_apply_groups(conn, keyword_id: int, group_ids: list[str], enabled: bool,
                      cooldown_seconds: int, replace_existing: bool) -> int:
    if replace_existing:
        if group_ids:
            placeholders = ",".join("?" for _ in group_ids)
            conn.execute(
                f"DELETE FROM group_keyword_bindings WHERE keyword_id=? AND group_id NOT IN ({placeholders})",
                (keyword_id, *group_ids),
            )
        else:
            conn.execute("DELETE FROM group_keyword_bindings WHERE keyword_id=?", (keyword_id,))
    for group_id in group_ids:
        conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
        conn.execute(
            "INSERT INTO group_keyword_bindings(group_id, keyword_id, enabled, cooldown_seconds) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(group_id, keyword_id) DO UPDATE SET "
            "enabled=excluded.enabled, cooldown_seconds=excluded.cooldown_seconds, "
            "updated_at=CURRENT_TIMESTAMP",
            (group_id, keyword_id, int(enabled), cooldown_seconds),
        )
    return len(group_ids)