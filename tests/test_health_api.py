"""API tests for GET /api/health build metadata.

Runs under pytest or directly: ``python tests/test_health_api.py``.
``APP_VERSION`` / ``APP_BUILD_TIME`` are normally baked into the image at
build time; here they are injected through the environment the same way.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_PATH"] = str(
    Path(tempfile.mkdtemp(prefix="health-test-")) / "bot.sqlite3"
)
os.environ["APP_VERSION"] = "abc12345"
os.environ["APP_BUILD_TIME"] = "2026-09-24 12:00:00 UTC"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import health as health_api  # noqa: E402
from app.db import init_db  # noqa: E402
from app.settings import get_settings  # noqa: E402


def make_client() -> TestClient:
    # Fresh temp DB per call: sibling test modules reassign DATABASE_PATH at
    # import/call time, so reusing one path can hit a foreign, partial schema.
    os.environ["DATABASE_PATH"] = str(
        Path(tempfile.mkdtemp(prefix="health-test-")) / "bot.sqlite3"
    )
    get_settings.cache_clear()
    init_db()
    app = FastAPI()
    app.include_router(health_api.router)
    return TestClient(app)


def test_health_reports_build_version():
    body = make_client().get("/api/health").json()
    assert body["ok"] is True, body
    assert body["version"] == "abc12345", body
    assert body["build_time"] == "2026-09-24 12:00:00 UTC", body
    assert "revision" in body, body


def test_health_defaults_to_dev_when_unset():
    saved = os.environ.pop("APP_VERSION", None)
    cwd = os.getcwd()
    try:
        # settings also reads APP_VERSION from .env/.env.prod (env_file);
        # chdir somewhere without those files to exercise the true default.
        os.chdir(tempfile.mkdtemp(prefix="health-cwd-"))
        body = make_client().get("/api/health").json()
        assert body["version"] == "dev", body
    finally:
        os.chdir(cwd)
        if saved is not None:
            os.environ["APP_VERSION"] = saved


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
