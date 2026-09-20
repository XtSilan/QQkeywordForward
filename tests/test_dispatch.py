"""Tests for the AIMD token bucket and the dispatch worker's DB transitions.

Runs under pytest or directly: ``python tests/test_dispatch.py``.

nonebot is not installed in the local dev environment, so a minimal fake
module tree is injected before importing ``app.services.dispatch``. The
worker tests run against a temporary SQLite file migrated with the real 006
and 007 scripts (which doubles as a migration smoke test).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_PATH"] = str(
    Path(tempfile.mkdtemp(prefix="dispatch-test-")) / "bot.sqlite3"
)

# --- fake nonebot so app.services.dispatch imports without the real package
_nonebot = types.ModuleType("nonebot")
_nonebot.logger = logging.getLogger("nonebot-test")
_nonebot.get_bots = lambda: {}
_adapters = types.ModuleType("nonebot.adapters")
_onebot = types.ModuleType("nonebot.adapters.onebot")
_v11 = types.ModuleType("nonebot.adapters.onebot.v11")


class _Bot:
    pass


_v11.Bot = _Bot
sys.modules["nonebot"] = _nonebot
sys.modules["nonebot.adapters"] = _adapters
sys.modules["nonebot.adapters.onebot"] = _onebot
sys.modules["nonebot.adapters.onebot.v11"] = _v11

from app.services import dispatch  # noqa: E402
from app.settings import get_settings  # noqa: E402


def fresh_db() -> None:
    """Point the app at a brand-new database and build the real schema."""
    os.environ["DATABASE_PATH"] = str(
        Path(tempfile.mkdtemp(prefix="dispatch-test-")) / "bot.sqlite3"
    )
    get_settings.cache_clear()
    conn = sqlite3.connect(os.environ["DATABASE_PATH"])
    conn.executescript(
        """
        CREATE TABLE app_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE keyword_hits(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sender_id TEXT NOT NULL DEFAULT '',
          sender_name TEXT NOT NULL DEFAULT '',
          keyword_text_snapshot TEXT NOT NULL DEFAULT '',
          message_text TEXT NOT NULL DEFAULT '',
          notify_status TEXT NOT NULL DEFAULT 'pending');
        CREATE TABLE notification_destinations(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL, address TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE notification_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hit_id INTEGER NOT NULL, destination_id INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_error TEXT, sent_at TEXT,
          UNIQUE(hit_id, destination_id));
        CREATE TABLE broadcast_tasks(
          id TEXT PRIMARY KEY, message_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued',
          sent_count INTEGER NOT NULL DEFAULT 0,
          failed_count INTEGER NOT NULL DEFAULT 0,
          started_at TEXT, finished_at TEXT);
        CREATE TABLE broadcast_task_groups(
          task_id TEXT NOT NULL, group_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued',
          scheduled_at TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          sent_at TEXT, message_id TEXT, error_text TEXT,
          PRIMARY KEY(task_id, group_id));
        """
    )
    for name in ("006_order_dedup.sql", "007_notification_order_fp.sql"):
        conn.executescript((ROOT / "migrations" / name).read_text(encoding="utf-8"))
    conn.commit()
    conn.close()


def reset_dispatch() -> None:
    dispatch._bucket = dispatch.AimdBucket()
    dispatch._group_sync_at = 0.0
    dispatch._sweep_at = 0.0


class FakeBot:
    def __init__(self, fail: bool = False, empty_id: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail
        self.empty_id = empty_id

    async def call_api(self, api, **kwargs):
        self.calls.append((api, kwargs))
        if self.fail:
            raise RuntimeError("napcat down")
        if self.empty_id:
            return {"message_id": ""}
        return {"message_id": "12345"}


def iso_in(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def add_job(
    priority: int = 1,
    expires_at: str | None = None,
    order_fp: str = "fp1",
    kind: str = "qq",
    address: str = "10001",
) -> int:
    """Insert hit + destination + job the way the handler would. Returns hit id."""
    with dispatch.connection() as conn:
        hit_id = conn.execute(
            "INSERT INTO keyword_hits(sender_name, sender_id, keyword_text_snapshot, message_text) "
            "VALUES ('张三', '999', '宜兴', '明天宜兴 对柜 38T')"
        ).lastrowid
        dest_id = conn.execute(
            "INSERT INTO notification_destinations(kind, address) VALUES (?, ?)",
            (kind, address),
        ).lastrowid
        conn.execute(
            "INSERT INTO notification_jobs(hit_id, destination_id, priority, expires_at, order_fp) "
            "VALUES (?, ?, ?, ?, ?)",
            (hit_id, dest_id, priority, expires_at, order_fp),
        )
        return int(hit_id)


def add_order(fp: str, sent: bool = True, last_seen: float | None = None) -> None:
    now = time.time()
    with dispatch.connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO orders(fp, dest, day, box, wt, core, phones, last_seen, sent_at, n_push, text) "
            "VALUES (?, '宜兴', '2026-09-21', '对柜', '38', '宜兴万石镇', '13000000000', ?, ?, 1, 'x')",
            (fp, last_seen if last_seen is not None else now, now if sent else None),
        )


def job_row(job_id: int) -> sqlite3.Row:
    with dispatch.connection() as conn:
        return conn.execute(
            "SELECT * FROM notification_jobs WHERE id=?", (job_id,)
        ).fetchone()


def hit_status(hit_id: int) -> str:
    with dispatch.connection() as conn:
        return conn.execute(
            "SELECT notify_status FROM keyword_hits WHERE id=?", (hit_id,)
        ).fetchone()["notify_status"]


def order_sent_at(fp: str):
    with dispatch.connection() as conn:
        row = conn.execute("SELECT sent_at FROM orders WHERE fp=?", (fp,)).fetchone()
        return row["sent_at"] if row else None


# ---------------------------------------------------------------------------
# bucket unit tests
# ---------------------------------------------------------------------------


def test_bucket_starts_conservative():
    bucket = dispatch.AimdBucket()
    assert bucket.rate == 0.5 and bucket.tokens == 3.0 and bucket.capacity == 3.0


def test_bucket_p1_keeps_one_token_reserved_for_p0():
    bucket = dispatch.AimdBucket(tokens=1.5)
    assert bucket.try_acquire(100.0, priority=1) is False  # needs 2 tokens
    assert bucket.try_acquire(100.0, priority=0) is True   # may use the reserve
    assert bucket.tokens == 0.5


def test_bucket_refills_at_rate():
    bucket = dispatch.AimdBucket(tokens=0.0)
    bucket.try_acquire(100.0)  # anchors last_refill
    assert bucket.try_acquire(104.0, priority=1) is True  # 4s * 0.5/s = 2 tokens
    assert abs(bucket.tokens - 1.0) < 1e-9


def test_bucket_failure_halves_rate_and_pauses():
    bucket = dispatch.AimdBucket()
    bucket.on_failure(100.0)
    assert bucket.rate == 0.25
    assert bucket.try_acquire(130.0, priority=0) is False  # still in the 60s pause
    assert bucket.try_acquire(161.0, priority=0) is True


def test_bucket_failure_floor_and_success_ceiling():
    bucket = dispatch.AimdBucket(rate=0.1)
    bucket.on_failure(0.0)
    assert bucket.rate == 0.1  # floor
    bucket = dispatch.AimdBucket(rate=1.0, paused_until=0.0)
    for _ in range(50):
        bucket.on_success()
    assert bucket.rate == 1.0  # ceiling, not 1.1
    bucket = dispatch.AimdBucket(rate=0.5)
    for _ in range(50):
        bucket.on_success()
    assert bucket.rate == 0.6


def test_bucket_failure_resets_success_streak():
    bucket = dispatch.AimdBucket(rate=0.5)
    for _ in range(49):
        bucket.on_success()
    bucket.on_failure(0.0)
    assert bucket.success_streak == 0


# ---------------------------------------------------------------------------
# worker tests
# ---------------------------------------------------------------------------


def setup_function():
    fresh_db()
    reset_dispatch()


def test_worker_sends_qq_job_and_marks_hit_sent():
    setup_function()
    hit_id = add_job(order_fp="fp1")
    add_order("fp1", sent=True)
    bot = FakeBot()
    outcome = asyncio.run(dispatch._work_once(bot))
    assert outcome == "worked"
    assert [c[0] for c in bot.calls] == ["send_private_msg"]
    job = job_row(1)
    assert job["status"] == "sent" and job["attempts"] == 1
    assert hit_status(hit_id) == "sent"
    assert order_sent_at("fp1") is not None


def test_worker_p0_preempts_p1():
    setup_function()
    add_job(priority=1, address="20001", order_fp="fp-slow")
    add_job(priority=0, address="20002", order_fp="fp-urgent")
    bot = FakeBot()
    asyncio.run(dispatch._work_once(bot))
    assert bot.calls[0][1]["user_id"] == 20002  # P0 first despite later id


def test_worker_throttled_when_p1_reserve_missing():
    setup_function()
    add_job(priority=1)
    dispatch._bucket = dispatch.AimdBucket(tokens=1.5)
    bot = FakeBot()
    outcome = asyncio.run(dispatch._work_once(bot))
    assert outcome == "throttled"
    assert bot.calls == []
    assert job_row(1)["status"] == "pending"  # not claimed while throttled


def test_worker_failure_retries_and_trips_circuit_breaker():
    setup_function()
    add_job(order_fp="fp1", expires_at=iso_in(900))
    add_order("fp1", sent=True)
    bot = FakeBot(fail=True)
    asyncio.run(dispatch._work_once(bot))
    job = job_row(1)
    assert job["status"] == "pending"  # back on the queue for a retry
    assert "napcat down" in job["last_error"]
    assert dispatch._bucket.rate == 0.25
    assert dispatch._bucket.paused_until > 0
    # retryable failure keeps the order marked so bursts don't re-enqueue
    assert order_sent_at("fp1") is not None


def test_worker_empty_message_id_counts_as_failure():
    setup_function()
    add_job(order_fp="fp1", expires_at=iso_in(900))
    bot = FakeBot(empty_id=True)
    asyncio.run(dispatch._work_once(bot))
    assert job_row(1)["status"] == "pending"
    assert "empty message_id" in job_row(1)["last_error"]
    assert dispatch._bucket.rate == 0.25


def test_expired_job_dropped_and_order_released():
    setup_function()
    hit_id = add_job(order_fp="fp1", expires_at=iso_in(-10))  # already past
    add_order("fp1", sent=True)
    bot = FakeBot()
    outcome = asyncio.run(dispatch._work_once(bot))
    assert outcome == "idle"
    assert bot.calls == []  # expired jobs are never sent
    job = job_row(1)
    assert job["status"] == "expired"
    assert hit_status(hit_id) == "expired"
    # released -> the next repost of the same order re-enqueues
    assert order_sent_at("fp1") is None


def test_release_keeps_order_marked_when_sibling_delivered():
    setup_function()
    # one hit, two destinations, same order fp; dest 1 already sent
    hit_id = add_job(order_fp="fp1", expires_at=iso_in(-10))
    with dispatch.connection() as conn:
        dest2 = conn.execute(
            "INSERT INTO notification_destinations(kind, address) VALUES ('qq', '10002')"
        ).lastrowid
        conn.execute(
            "INSERT INTO notification_jobs(hit_id, destination_id, priority, expires_at, order_fp, status) "
            "VALUES (?, ?, 1, ?, 'fp1', 'sent')",
            (hit_id, dest2, iso_in(900)),
        )
    add_order("fp1", sent=True)
    asyncio.run(dispatch._work_once(FakeBot()))
    assert job_row(1)["status"] == "expired"
    assert order_sent_at("fp1") is not None  # sibling delivered, stays armed
    assert hit_status(hit_id) == "sent"      # at least one destination got it


def test_failed_past_expiry_releases_order():
    setup_function()
    add_job(order_fp="fp1", expires_at=iso_in(5))
    add_order("fp1", sent=True)
    bot = FakeBot(fail=True)
    # fail once while the job is still alive -> stays pending
    asyncio.run(dispatch._work_once(bot))
    assert job_row(1)["status"] == "pending"
    # time passes beyond expiry; the sweeper drops it and releases the order
    with dispatch.connection() as conn:
        conn.execute(
            "UPDATE notification_jobs SET expires_at=? WHERE id=1", (iso_in(-1),)
        )
    asyncio.run(dispatch._work_once(FakeBot()))
    assert job_row(1)["status"] == "expired"
    assert order_sent_at("fp1") is None


def test_email_jobs_bypass_the_bucket():
    setup_function()
    add_job(kind="email", address="ops@example.com", order_fp="fp1")
    dispatch._bucket.paused_until = dispatch._now() + 3600  # circuit broken
    sent: list[tuple] = []

    async def fake_email(settings, recipient, subject, body):
        sent.append((recipient, subject))

    original = dispatch.send_smtp_email
    dispatch.send_smtp_email = fake_email
    try:
        outcome = asyncio.run(dispatch._work_once(FakeBot()))
    finally:
        dispatch.send_smtp_email = original
    assert outcome == "worked"
    assert sent and sent[0][0] == "ops@example.com"
    assert job_row(1)["status"] == "sent"


def test_broadcast_uses_bucket_and_empty_id_is_failed():
    setup_function()
    with dispatch.connection() as conn:
        conn.execute(
            "INSERT INTO broadcast_tasks(id, message_json, status) VALUES ('t1', '[]', 'queued')"
        )
        conn.execute(
            "INSERT INTO broadcast_task_groups(task_id, group_id, status, scheduled_at) "
            "VALUES ('t1', '555', 'queued', ?)",
            (iso_in(-1),),
        )
    bot = FakeBot(empty_id=True)
    outcome = asyncio.run(dispatch._work_once(bot))
    assert outcome == "worked"
    assert [c[0] for c in bot.calls] == ["send_group_msg"]
    with dispatch.connection() as conn:
        group = conn.execute(
            "SELECT status, error_text FROM broadcast_task_groups WHERE task_id='t1'"
        ).fetchone()
        task = conn.execute(
            "SELECT status, failed_count FROM broadcast_tasks WHERE id='t1'"
        ).fetchone()
    assert group["status"] == "failed" and "empty message_id" in group["error_text"]
    assert task["status"] == "completed_with_errors" and task["failed_count"] == 1
    assert dispatch._bucket.rate == 0.25  # account-level signal


def test_broadcast_exception_does_not_feed_bucket():
    setup_function()
    with dispatch.connection() as conn:
        conn.execute(
            "INSERT INTO broadcast_tasks(id, message_json, status) VALUES ('t1', '[]', 'queued')"
        )
        conn.execute(
            "INSERT INTO broadcast_task_groups(task_id, group_id, status, scheduled_at) "
            "VALUES ('t1', '555', 'queued', ?)",
            (iso_in(-1),),
        )
    asyncio.run(dispatch._work_once(FakeBot(fail=True)))
    with dispatch.connection() as conn:
        group = conn.execute(
            "SELECT status FROM broadcast_task_groups WHERE task_id='t1'"
        ).fetchone()
    assert group["status"] == "failed"
    assert dispatch._bucket.rate == 0.5  # group-level failure, rate untouched


def test_sweep_prunes_old_orders_and_requeues_orphans():
    setup_function()
    add_order("fp-old", last_seen=time.time() - 8 * 86400)
    add_order("fp-new")
    add_job(order_fp="fp-new")
    with dispatch.connection() as conn:
        conn.execute("UPDATE notification_jobs SET status='sending' WHERE id=1")
    dispatch._sweep()
    with dispatch.connection() as conn:
        fps = [r["fp"] for r in conn.execute("SELECT fp FROM orders").fetchall()]
    assert fps == ["fp-new"]
    assert job_row(1)["status"] == "pending"  # crash orphan recovered


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
