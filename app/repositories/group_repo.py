"""Data-access functions for groups and per-group notification switches."""
from __future__ import annotations

from typing import Any

from app.db import row_dict


# SQL shared by several call sites: enable a channel for a group without ever
# turning an already-enabled channel off.
_ENABLE_CHANNELS = (
    "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id) DO UPDATE SET "
    "qq_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.qq_enabled END, "
    "email_enabled=CASE WHEN ?=1 THEN 1 ELSE group_notification_settings.email_enabled END, "
    "updated_at=CURRENT_TIMESTAMP"
)

# SQL shared by destination create/update/delete: derive the switches from the
# enabled destinations currently bound to the group.
_RECOMPUTE_CHANNELS = (
    "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
    "VALUES (?, "
    "EXISTS(SELECT 1 FROM notification_destination_bindings b "
    "JOIN notification_destinations d ON d.id=b.destination_id "
    "WHERE b.group_id=? AND d.kind='qq' AND d.enabled=1), "
    "EXISTS(SELECT 1 FROM notification_destination_bindings b "
    "JOIN notification_destinations d ON d.id=b.destination_id "
    "WHERE b.group_id=? AND d.kind='email' AND d.enabled=1), CURRENT_TIMESTAMP) "
    "ON CONFLICT(group_id) DO UPDATE SET qq_enabled=excluded.qq_enabled, "
    "email_enabled=excluded.email_enabled, updated_at=CURRENT_TIMESTAMP"
)

# SQL shared by the explicit per-group settings endpoints: set both switches.
_SET_CHANNELS = (
    "INSERT INTO group_notification_settings(group_id, qq_enabled, email_enabled, updated_at) "
    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id) DO UPDATE SET "
    "qq_enabled=excluded.qq_enabled, email_enabled=excluded.email_enabled, updated_at=CURRENT_TIMESTAMP"
)


# -- groups ------------------------------------------------------------------

def list_groups(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT group_id, name, avatar_url, enabled, last_synced_at "
        "FROM groups ORDER BY name COLLATE NOCASE, group_id"
    ).fetchall()
    return [row_dict(row) for row in rows]


def upsert_group(conn, group_id: str, name: str = "", avatar_url: str = "") -> None:
    conn.execute(
        "INSERT INTO groups(group_id, name, avatar_url, last_synced_at) "
        "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(group_id) DO UPDATE SET name=excluded.name, "
        "avatar_url=excluded.avatar_url, last_synced_at=CURRENT_TIMESTAMP",
        (group_id, name, avatar_url),
    )


def ensure_group(conn, group_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))


# -- per-group notification switches -----------------------------------------

def enable_channels(conn, group_id: str, qq: bool, email: bool) -> None:
    """Turn channels on without turning others off (CASE WHEN guard)."""
    conn.execute(_ENABLE_CHANNELS, (group_id, int(qq), int(email), int(qq), int(email)))


def recompute_channels(conn, group_id: str) -> None:
    """Re-derive switches from the group's enabled destination bindings."""
    ensure_group(conn, group_id)
    conn.execute(_RECOMPUTE_CHANNELS, (group_id, group_id, group_id))


def set_channels(conn, group_id: str, qq: bool, email: bool) -> None:
    ensure_group(conn, group_id)
    conn.execute(_SET_CHANNELS, (group_id, int(qq), int(email)))


def get_channels(conn, group_id: str) -> tuple[bool, bool]:
    row = conn.execute(
        "SELECT qq_enabled, email_enabled FROM group_notification_settings WHERE group_id=?",
        (group_id,),
    ).fetchone()
    if not row:
        return False, False
    return bool(row["qq_enabled"]), bool(row["email_enabled"])