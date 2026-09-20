"""API test for the dashboard summary.

Runs under pytest or directly: ``python tests/test_dashboard_api.py``.

The stat the dashboard shows instead of the old broadcast counter is "how many
alert notifications went out today", so the counting rules matter: only rows the
dispatcher really delivered (``status='sent'`` with a ``sent_at``) count, and
only from today. Note the two storage formats involved: ``notification_jobs.
sent_at`` is SQLite's ``CURRENT_TIMESTAMP`` ("YYYY-MM-DD HH:MM:SS"), while
``keyword_hits.hit_at`` is an aware UTC isoformat.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_PATH"] = str(
    Path(tempfile.mkdtemp(prefix="dashboard-test-")) / "bot.sqlite3"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import dashboard as dashboard_api  # noqa: E402
from app.db import connection, init_db  # noqa: E402
from app.repositories import group_repo  # noqa: E402
from app.settings import get_settings  # noqa: E402


def make_client() -> TestClient:
    os.environ["DATABASE_PATH"] = str(
        Path(tempfile.mkdtemp(prefix="dashboard-test-")) / "bot.sqlite3"
    )
    get_settings.cache_clear()
    init_db()
    app = FastAPI()
    app.include_router(dashboard_api.router)
    return TestClient(app)


def sent_stamp(days_ago: int = 0) -> str:
    """A ``CURRENT_TIMESTAMP``-shaped UTC stamp, the format the dispatcher writes."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def add_job(status: str, sent_at: str | None, group_id: str = "g1", hit_days_ago: int = 0) -> None:
    hit_at = (
        datetime.now(timezone.utc) - timedelta(days=hit_days_ago)
    ).isoformat()
    with connection() as conn:
        group_repo.ensure_group(conn, group_id)
        hit_id = int(
            conn.execute(
                "INSERT INTO keyword_hits(group_id, group_name, sender_id, sender_name, keyword_id, "
                "keyword_text_snapshot, message_json, message_text, message_id, hit_at, notify_status) "
                "VALUES (?, '', '1', 'tester', NULL, '宜兴', '[]', '明天宜兴', ?, ?, 'sent')",
                (group_id, f"m{status}{sent_at}", hit_at),
            ).lastrowid
        )
        destination_id = int(
            conn.execute(
                "INSERT INTO notification_destinations(kind, address) VALUES ('qq', ?)",
                (f"9{hit_id}",),
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO notification_jobs(hit_id, destination_id, status, sent_at) VALUES (?, ?, ?, ?)",
            (hit_id, destination_id, status, sent_at),
        )


def test_counts_only_alerts_delivered_today():
    client = make_client()
    add_job("sent", sent_stamp(0))
    add_job("sent", sent_stamp(2))          # delivered, but not today
    add_job("pending", None)                # queued, never sent
    add_job("failed", sent_stamp(0))        # has a timestamp but did not deliver
    add_job("expired", sent_stamp(0))       # gave up before sending

    stats = client.get("/api/dashboard").json()["stats"]
    assert stats["alerts_sent_today"] == 1, stats


def test_counts_every_destination_of_the_same_day():
    client = make_client()
    add_job("sent", sent_stamp(0))
    add_job("sent", sent_stamp(0))
    stats = client.get("/api/dashboard").json()["stats"]
    assert stats["alerts_sent_today"] == 2, stats


def test_hits_today_and_group_count():
    client = make_client()
    add_job("sent", sent_stamp(0))
    add_job("pending", None, group_id="g2", hit_days_ago=3)

    stats = client.get("/api/dashboard").json()["stats"]
    assert stats["keyword_hits_today"] == 1, stats  # the 3-day-old hit is excluded
    assert stats["groups"] == 2, stats


def main() -> int:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface everything in the runner
            failed += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {name}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())