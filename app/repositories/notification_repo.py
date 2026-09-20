"""Data-access functions for notification destinations and their bindings."""
from __future__ import annotations

from typing import Any

from app.db import row_dict


def list_destinations(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT d.id, d.kind, d.address, d.display_name, d.enabled, d.created_at, "
        "COALESCE(GROUP_CONCAT(b.group_id), '') AS group_ids_csv "
        "FROM notification_destinations d LEFT JOIN notification_destination_bindings b "
        "ON b.destination_id=d.id GROUP BY d.id ORDER BY d.kind, d.id DESC"
    ).fetchall()
    result = []
    for row in rows:
        item = row_dict(row)
        item["group_ids"] = [value for value in item.pop("group_ids_csv", "").split(",") if value]
        result.append(item)
    return result


def find_by_address(conn, kind: str, address: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM notification_destinations WHERE kind=? AND address=?",
        (kind, address),
    ).fetchone()
    return int(row["id"]) if row else None


def insert(conn, kind: str, address: str, display_name: str) -> int:
    cursor = conn.execute(
        "INSERT INTO notification_destinations(kind, address, display_name) VALUES (?, ?, ?)",
        (kind, address, display_name),
    )
    return int(cursor.lastrowid)


def enable(conn, destination_id: int, display_name: str) -> None:
    conn.execute(
        "UPDATE notification_destinations SET display_name=?, enabled=1 WHERE id=?",
        (display_name, destination_id),
    )


def update(conn, destination_id: int, kind: str, address: str, display_name: str, enabled: bool) -> bool:
    cursor = conn.execute(
        "UPDATE notification_destinations SET kind=?, address=?, display_name=?, enabled=? WHERE id=?",
        (kind, address, display_name, int(enabled), destination_id),
    )
    return cursor.rowcount > 0


def delete(conn, destination_id: int) -> bool:
    cursor = conn.execute("DELETE FROM notification_destinations WHERE id=?", (destination_id,))
    return cursor.rowcount > 0


def purge_references(conn, destination_id: int) -> None:
    """Remove rows that reference a destination before deleting it.

    Done explicitly because the schema keeps foreign-key enforcement on.
    """
    conn.execute("DELETE FROM notification_jobs WHERE destination_id=?", (destination_id,))
    conn.execute("DELETE FROM keyword_notification_bindings WHERE destination_id=?", (destination_id,))
    conn.execute("DELETE FROM notification_destination_bindings WHERE destination_id=?", (destination_id,))


# -- group <-> destination bindings ------------------------------------------

def bind_group(conn, group_id: str, destination_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO notification_destination_bindings(group_id, destination_id) VALUES (?, ?)",
        (group_id, destination_id),
    )


def clear_group(conn, group_id: str) -> None:
    conn.execute("DELETE FROM notification_destination_bindings WHERE group_id=?", (group_id,))


def clear_destination(conn, destination_id: int) -> None:
    conn.execute("DELETE FROM notification_destination_bindings WHERE destination_id=?", (destination_id,))


def destination_groups(conn, destination_id: int) -> list[str]:
    return [
        str(row["group_id"])
        for row in conn.execute(
            "SELECT group_id FROM notification_destination_bindings WHERE destination_id=?",
            (destination_id,),
        ).fetchall()
    ]


def group_destination_ids(conn, group_id: str) -> list[int]:
    return [
        int(row["destination_id"])
        for row in conn.execute(
            "SELECT destination_id FROM notification_destination_bindings WHERE group_id=?",
            (group_id,),
        ).fetchall()
    ]