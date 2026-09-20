"""API tests for the order-dedup settings endpoints (P3).

Runs under pytest or directly: ``python tests/test_settings_api.py``.
Uses a temporary database migrated by the real ``init_db``; ``admin_guard``
passes because the default ``app_env`` is "dev".
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_PATH"] = str(
    Path(tempfile.mkdtemp(prefix="settings-api-test-")) / "bot.sqlite3"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import settings as settings_api  # noqa: E402
from app.db import connection, init_db  # noqa: E402
from app.services import orders  # noqa: E402
from app.settings import get_settings  # noqa: E402


def make_client() -> TestClient:
    """Fresh database per test so seeded defaults are observable."""
    os.environ["DATABASE_PATH"] = str(
        Path(tempfile.mkdtemp(prefix="settings-api-test-")) / "bot.sqlite3"
    )
    get_settings.cache_clear()
    init_db()
    app = FastAPI()
    app.include_router(settings_api.router)
    return TestClient(app)


def test_get_returns_seeded_defaults():
    client = make_client()
    body = client.get("/api/settings/order-dedup").json()
    assert body == {
        "enabled": True,
        "similarity": 0.8,
        "window_minutes": 60,
        "max_push_per_order": 2,
        "new_phone_repush": True,
        "ad_filter_enabled": True,
        "ad_keywords": "招工,日结,时薪,暑假工",
    }, body


def test_put_roundtrips_through_service_layer():
    client = make_client()
    response = client.put(
        "/api/settings/order-dedup",
        json={
            "enabled": False,
            "similarity": 0.7,
            "window_minutes": 30,
            "max_push_per_order": 3,
            "new_phone_repush": False,
            "ad_filter_enabled": False,
            # 中文逗号 + 空格应在写入时归一化
            "ad_keywords": "招工， 日结，，临时工 ",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["saved"] is True

    body = client.get("/api/settings/order-dedup").json()
    assert body["enabled"] is False
    assert body["similarity"] == 0.7
    assert body["window_minutes"] == 30
    assert body["max_push_per_order"] == 3
    assert body["new_phone_repush"] is False
    assert body["ad_filter_enabled"] is False
    assert body["ad_keywords"] == "招工,日结,临时工"

    # 服务层（机器人实际读取的路径）看到同样的值
    with connection() as conn:
        dedup = orders.load_settings(conn)
    assert dedup.enabled is False
    assert dedup.similarity == 0.7
    assert dedup.window_seconds == 1800.0
    assert dedup.max_push == 3
    assert dedup.ad_keywords == ("招工", "日结", "临时工")


def test_put_validates_ranges():
    client = make_client()
    assert client.put("/api/settings/order-dedup", json={"similarity": 1.5}).status_code == 422
    assert client.put("/api/settings/order-dedup", json={"similarity": 0.05}).status_code == 422
    assert client.put("/api/settings/order-dedup", json={"window_minutes": 0}).status_code == 422
    assert client.put("/api/settings/order-dedup", json={"max_push_per_order": 0}).status_code == 422


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
