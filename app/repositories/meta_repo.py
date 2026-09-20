"""Data-access functions for the app_meta key/value store."""
from __future__ import annotations


def get(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def get_many(conn, keys: list[str]) -> dict[str, str]:
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"SELECT key, value FROM app_meta WHERE key IN ({placeholders})", keys
    ).fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def get_by_prefix(conn, prefix: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT key, value FROM app_meta WHERE key LIKE ?", (prefix + "%",)
    ).fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def set_many(conn, values: dict[str, str]) -> None:
    for key, value in values.items():
        set(conn, key, value)


def set_if_absent(conn, key: str, value: str) -> bool:
    """Insert only when the key is missing. Returns True when it was inserted."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO app_meta(key, value) VALUES (?, ?)", (key, value)
    )
    return cursor.rowcount > 0