from pathlib import Path
import sqlite3
from contextlib import contextmanager
from typing import Any

from app.settings import get_settings


def row_dict(row: Any) -> dict[str, Any]:
    """Convert a ``sqlite3.Row`` into a plain dict."""
    return dict(row)


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def load_migration(filename: str) -> str:
    """Read a migration script from ``migrations/``.

    Guards that decide *whether* a migration runs stay in Python; only the SQL
    itself lives in the versioned ``.sql`` files.
    """
    return (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")


def _migrate_broadcast_interval(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='broadcast_tasks'"
    ).fetchone()
    normalized = "".join((row[0] if row and row[0] else "").lower().split())
    if "check(interval_seconds>=12)" not in normalized:
        return

    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript(load_migration("002_broadcast_interval.sql"))
    connection.execute("PRAGMA foreign_keys = ON")


def _migrate_broadcast_interval_floor(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='broadcast_tasks'"
    ).fetchone()
    normalized = "".join((row[0] if row and row[0] else "").lower().split())
    if "check(interval_seconds>=5)" not in normalized:
        return

    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript(load_migration("005_broadcast_interval_floor.sql"))
    connection.execute("PRAGMA foreign_keys = ON")


def _migrate_duplicate_message_cooldowns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(keyword_message_cooldowns)"
        ).fetchall()
    }
    if "keyword_id" not in columns:
        return

    connection.executescript(load_migration("003_duplicate_message_cooldowns.sql"))


def _migrate_keyword_sort_order(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(keyword_rules)"
        ).fetchall()
    }
    if "sort_order" in columns:
        return
    connection.executescript(load_migration("004_keyword_sort_order.sql"))


def _migrate_order_dedup(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('orders', 'msgs')"
        ).fetchall()
    }
    job_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(notification_jobs)").fetchall()
    }
    if {"orders", "msgs"} <= tables and "priority" in job_columns:
        return
    connection.executescript(load_migration("006_order_dedup.sql"))


def _migrate_notification_order_fp(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(notification_jobs)"
        ).fetchall()
    }
    if "order_fp" in columns:
        return
    connection.executescript(load_migration("007_notification_order_fp.sql"))


def init_db() -> None:
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as connection:
        # WAL lets the dispatch worker read while the bot handler writes.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(load_migration("001_initial.sql"))
        _migrate_broadcast_interval(connection)
        _migrate_broadcast_interval_floor(connection)
        _migrate_duplicate_message_cooldowns(connection)
        _migrate_keyword_sort_order(connection)
        _migrate_order_dedup(connection)
        _migrate_notification_order_fp(connection)
        connection.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('config_revision', '1')"
        )
        connection.commit()


@contextmanager
def connection():
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def config_revision() -> int:
    with connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'config_revision'"
        ).fetchone()
        return int(row["value"]) if row else 0


def bump_config_revision() -> int:
    with connection() as conn:
        current = config_revision()
        next_value = current + 1
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES ('config_revision', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(next_value),),
        )
        return next_value
