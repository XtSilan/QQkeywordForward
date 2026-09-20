"""API tests for the keyword-hit history listing.

Runs under pytest or directly: ``python tests/test_history_api.py``.

Covers the date-range filter the UI's day picker drives (the browser converts a
local day into UTC instants), the group filter, ordering/pagination, and the
query-plan guard that keeps the listing off a full table scan.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_PATH"] = str(
    Path(tempfile.mkdtemp(prefix="history-api-test-")) / "bot.sqlite3"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import history as history_api  # noqa: E402
from app.db import connection, init_db  # noqa: E402
from app.repositories import group_repo  # noqa: E402
from app.settings import get_settings  # noqa: E402

# Stored the way app/nonebot_bot.py writes hit_at: aware UTC isoformat.
# In UTC+8 these land at 00:30 on the 20th, 13:00 on the 20th, 00:30 on the
# 21st and 10:00 on the 18th respectively.
EARLY_20TH = "2026-09-19T16:30:00.000000+00:00"
NOON_20TH = "2026-09-20T05:00:00.000000+00:00"
EARLY_21ST = "2026-09-20T16:30:00.000000+00:00"
THE_18TH = "2026-09-18T02:00:00.000000+00:00"

# The UTC bounds a browser in UTC+8 sends for the local day 2026-09-20.
DAY_20TH = {
    "since": "2026-09-19T16:00:00.000Z",
    "until": "2026-09-20T16:00:00.000Z",
}


def make_client() -> TestClient:
    os.environ["DATABASE_PATH"] = str(
        Path(tempfile.mkdtemp(prefix="history-api-test-")) / "bot.sqlite3"
    )
    get_settings.cache_clear()
    init_db()
    app = FastAPI()
    app.include_router(history_api.router)
    return TestClient(app)


def add_hit(group_id: str, hit_at: str, keyword_id: int | None = None, text: str = "明天宜兴") -> int:
    with connection() as conn:
        group_repo.ensure_group(conn, group_id)
        cursor = conn.execute(
            "INSERT INTO keyword_hits(group_id, group_name, sender_id, sender_name, keyword_id, "
            "keyword_text_snapshot, message_json, message_text, message_id, hit_at, notify_status) "
            "VALUES (?, '', '1', 'tester', ?, '宜兴', '[]', ?, 'mid', ?, 'sent')",
            (group_id, keyword_id, text, hit_at),
        )
        return int(cursor.lastrowid)


def add_keyword_rule(display_text: str = "宜兴") -> int:
    with connection() as conn:
        return int(
            conn.execute(
                "INSERT INTO keyword_rules(display_text, pattern) VALUES (?, ?)",
                (display_text, display_text),
            ).lastrowid
        )


def test_unfiltered_listing_returns_everything_newest_first():
    client = make_client()
    add_hit("g1", THE_18TH)
    add_hit("g1", EARLY_21ST)
    add_hit("g2", NOON_20TH)

    body = client.get("/api/history").json()
    assert [item["hit_at"] for item in body["items"]] == [EARLY_21ST, NOON_20TH, THE_18TH]
    assert body["total"] == 3


def test_date_range_keeps_only_the_picked_local_day():
    client = make_client()
    add_hit("g1", EARLY_20TH)
    add_hit("g1", NOON_20TH)
    add_hit("g1", EARLY_21ST)   # local 21st, so outside the picked day
    add_hit("g1", THE_18TH)

    body = client.get("/api/history", params=DAY_20TH).json()
    assert [item["hit_at"] for item in body["items"]] == [NOON_20TH, EARLY_20TH]
    assert body["total"] == 2


def test_range_bounds_are_normalised_to_the_stored_shape():
    """The bound arrives as `...Z`; rows are stored with `+00:00`, and a naive
    value is treated as UTC. All three must select the same rows."""
    client = make_client()
    add_hit("g1", EARLY_20TH)
    add_hit("g1", EARLY_21ST)

    for params in (
        DAY_20TH,
        {"since": "2026-09-19T16:00:00+00:00", "until": "2026-09-20T16:00:00+00:00"},
        {"since": "2026-09-19T16:00:00", "until": "2026-09-20T16:00:00"},
    ):
        body = client.get("/api/history", params=params).json()
        assert [item["hit_at"] for item in body["items"]] == [EARLY_20TH], params


def test_group_filter_combines_with_the_date_range():
    client = make_client()
    add_hit("g1", EARLY_20TH)
    add_hit("g2", NOON_20TH)
    add_hit("g2", EARLY_21ST)

    body = client.get("/api/history", params={"group_id": "g2", **DAY_20TH}).json()
    assert [item["hit_at"] for item in body["items"]] == [NOON_20TH]
    assert body["total"] == 1

    assert client.get("/api/history", params={"group_id": "g1"}).json()["total"] == 1
    assert client.get("/api/history", params={"group_id": "missing"}).json()["total"] == 0


def test_keyword_filter_and_pagination():
    client = make_client()
    keyword_id = add_keyword_rule()
    for index in range(5):
        add_hit("g1", f"2026-09-20T0{index}:00:00.000000+00:00", keyword_id=keyword_id)
    add_hit("g1", "2026-09-20T09:00:00.000000+00:00")  # no keyword_id

    body = client.get("/api/history", params={"keyword_id": keyword_id, "limit": 2}).json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["items"][0]["hit_at"] == "2026-09-20T04:00:00.000000+00:00"

    second = client.get(
        "/api/history", params={"keyword_id": keyword_id, "limit": 2, "offset": 2}
    ).json()
    assert [item["hit_at"] for item in second["items"]] == [
        "2026-09-20T02:00:00.000000+00:00",
        "2026-09-20T01:00:00.000000+00:00",
    ]


def test_rejects_a_malformed_bound():
    client = make_client()
    assert client.get("/api/history", params={"since": "yesterday"}).status_code == 422
    assert client.get("/api/history", params={"limit": 500}).status_code == 422


def test_listing_plans_stay_on_an_index():
    """Regression guard for the full-scan bug: the old parameterised
    ``(? IS NULL OR group_id=?)`` predicate could not use either index, and the
    global listing had no hit_at index at all."""
    make_client()
    with connection() as conn:
        plans = {
            "group": conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM keyword_hits WHERE group_id=? "
                "ORDER BY hit_at DESC LIMIT 20",
                ("g1",),
            ).fetchall(),
            "range": conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM keyword_hits WHERE hit_at >= ? AND hit_at < ? "
                "ORDER BY hit_at DESC LIMIT 20",
                ("a", "b"),
            ).fetchall(),
            "global": conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM keyword_hits ORDER BY hit_at DESC LIMIT 20"
            ).fetchall(),
        }
    steps = {name: [row["detail"] for row in rows] for name, rows in plans.items()}

    assert any("idx_keyword_hits_group_time" in step for step in steps["group"]), steps
    assert any("idx_keyword_hits_hit_at" in step for step in steps["range"]), steps
    assert any("idx_keyword_hits_hit_at" in step for step in steps["global"]), steps
    for name, detail in steps.items():
        assert not any("SCAN keyword_hits" == step for step in detail), (name, detail)
        assert not any("TEMP B-TREE" in step for step in detail), (name, detail)


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