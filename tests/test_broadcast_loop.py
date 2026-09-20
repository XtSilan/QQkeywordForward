"""API tests for auto-looping broadcast tasks.

Runs under pytest or directly: ``python tests/test_broadcast_loop.py``.

Uses a temporary database built by the real ``init_db`` (so migration 009 is
exercised) and ``admin_guard`` passes because ``app_env`` defaults to "dev".
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
    Path(tempfile.mkdtemp(prefix="broadcast-loop-test-")) / "bot.sqlite3"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import broadcast as broadcast_api  # noqa: E402
from app.db import connection, init_db  # noqa: E402
from app.repositories import broadcast_repo  # noqa: E402
from app.settings import get_settings  # noqa: E402


def make_client() -> TestClient:
    """Fresh database per test so seeded defaults are observable."""
    os.environ["DATABASE_PATH"] = str(
        Path(tempfile.mkdtemp(prefix="broadcast-loop-test-")) / "bot.sqlite3"
    )
    get_settings.cache_clear()
    init_db()
    app = FastAPI()
    app.include_router(broadcast_api.router)
    return TestClient(app)


def create_task(client: TestClient, **overrides) -> str:
    payload = {
        "title": "循环通知",
        "group_ids": ["1001", "1002", "1003"],
        "message": [{"type": "text", "data": {"text": "hello"}}],
        "interval_seconds": 5,
        "loop_total": 3,
        "loop_interval_seconds": 30,
    }
    payload.update(overrides)
    response = client.post("/api/broadcast-tasks", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def iso_in(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def test_create_opens_round_one_and_staggers_the_groups():
    client = make_client()
    task_id = create_task(client)

    with connection() as conn:
        task = broadcast_repo.intervals(conn, task_id)
        rows = conn.execute(
            "SELECT scheduled_at FROM broadcast_task_groups WHERE task_id=? ORDER BY rowid",
            (task_id,),
        ).fetchall()

    assert task["loop_total"] == 3
    assert task["loop_current"] == 1
    assert task["loop_interval_seconds"] == 30
    # the first group is due at once and the rest follow at the group delay
    assert rows[0]["scheduled_at"] < iso_in(2)
    assert rows[1]["scheduled_at"] > iso_in(3)
    assert rows[2]["scheduled_at"] > iso_in(8)

    listed = client.get("/api/broadcast-tasks").json()[0]
    assert listed["loop_total"] == 3 and listed["loop_current"] == 1
    assert listed["round_sent"] == 0 and listed["total_count"] == 3


def test_creating_without_loop_stays_a_single_pass():
    client = make_client()
    task_id = create_task(client, loop_total=0)
    with connection() as conn:
        task = broadcast_repo.intervals(conn, task_id)
    assert task["loop_total"] == 0
    assert task["loop_current"] == 0  # no round counter for a one-shot task


def test_round_gap_can_change_while_the_task_is_still_queued():
    client = make_client()
    task_id = create_task(client)
    response = client.put(
        f"/api/broadcast-tasks/{task_id}", json={"loop_interval_seconds": 45}
    )
    assert response.status_code == 200, response.text
    assert response.json()["loop_interval_seconds"] == 45
    with connection() as conn:
        assert broadcast_repo.intervals(conn, task_id)["loop_interval_seconds"] == 45


def test_group_delay_requires_a_paused_task():
    client = make_client()
    task_id = create_task(client)

    response = client.put(f"/api/broadcast-tasks/{task_id}", json={"interval_seconds": 9})
    assert response.status_code == 409, response.text  # queued: would re-space the queue

    assert client.post(f"/api/broadcast-tasks/{task_id}/pause").status_code == 200
    response = client.put(f"/api/broadcast-tasks/{task_id}", json={"interval_seconds": 9})
    assert response.status_code == 200, response.text
    with connection() as conn:
        assert broadcast_repo.intervals(conn, task_id)["interval_seconds"] == 9


def test_payload_bounds_and_missing_task():
    client = make_client()
    assert (
        client.post(
            "/api/broadcast-tasks",
            json={
                "title": "x",
                "group_ids": ["1"],
                "message": [{"type": "text", "data": {"text": "x"}}],
                "loop_total": 51,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/broadcast-tasks",
            json={
                "title": "x",
                "group_ids": ["1"],
                "message": [{"type": "text", "data": {"text": "x"}}],
                "loop_interval_seconds": 1,  # below the round-gap floor
            },
        ).status_code
        == 422
    )

    task_id = create_task(client)
    assert client.put(f"/api/broadcast-tasks/{task_id}", json={}).status_code == 422
    assert (
        client.put("/api/broadcast-tasks/missing", json={"loop_interval_seconds": 10}).status_code
        == 404
    )


def test_start_next_round_resets_round_progress_only():
    client = make_client()
    task_id = create_task(client)

    with connection() as conn:
        # pretend round one was delivered
        conn.execute(
            "UPDATE broadcast_task_groups SET status='sent' WHERE task_id=?", (task_id,)
        )
        conn.execute("UPDATE broadcast_tasks SET sent_count=3 WHERE id=?", (task_id,))
        assert broadcast_repo.list_tasks(conn, 5)[0]["round_sent"] == 3

        broadcast_repo.start_next_round(conn, task_id, 5, 30)

        listed = broadcast_repo.list_tasks(conn, 5)[0]
        assert listed["loop_current"] == 2
        assert listed["round_sent"] == 0      # a fresh round
        assert listed["sent_count"] == 3      # cumulative total survives
        rows = conn.execute(
            "SELECT status, scheduled_at FROM broadcast_task_groups "
            "WHERE task_id=? ORDER BY rowid",
            (task_id,),
        ).fetchall()

    assert [row["status"] for row in rows] == ["queued", "queued", "queued"]
    # the round waits out the gap, then keeps the original order and spacing
    assert rows[0]["scheduled_at"] > iso_in(25)
    assert rows[1]["scheduled_at"] > iso_in(29)


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