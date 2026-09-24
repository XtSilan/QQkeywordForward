"""API tests for GET /api/release-notes: short SHA + Actions CI badges.

Runs under pytest or directly: ``python tests/test_release_notes.py``.
GitHub is stubbed with httpx.MockTransport so the suite never hits the network.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import releases as releases_api  # noqa: E402


def make_commit(sha: str, title: str, body: str = "") -> dict[str, Any]:
    message = title if not body else f"{title}\n\n{body}"
    return {
        "sha": sha,
        "commit": {"message": message, "author": {"date": "2026-09-24T06:00:00Z"}},
    }


def make_run(sha: str, status: str, conclusion: str | None = None) -> dict[str, Any]:
    return {"head_sha": sha, "status": status, "conclusion": conclusion}


@contextmanager
def stub_github(handler: Any) -> Iterator[None]:
    """Route every httpx.AsyncClient (release_notes uses one) through `handler`."""
    original = httpx.AsyncClient

    class Patched(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = Patched  # type: ignore[misc]
    releases_api._items = []
    releases_api._cached_at = 0.0
    try:
        yield
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]


def get_release_notes(handler: Any) -> dict[str, Any]:
    app = FastAPI()
    app.include_router(releases_api.router)
    with stub_github(handler):
        return TestClient(app).get("/api/release-notes").json()


def test_release_notes_include_short_sha_and_ci_badges() -> None:
    commits = [
        make_commit("5c7ccf686fdcb510dbdd012992251022b7514406", "fix docker", "body"),
        make_commit("58742cfafddf3bdda32ea135e86bd82d70e57281", "feat updater"),
        make_commit("1111111122222222333333334444444455555555", "no ci run"),
        make_commit("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "in progress"),
    ]
    runs = [
        make_run("5c7ccf686fdcb510dbdd012992251022b7514406", "completed", "success"),
        make_run("58742cfafddf3bdda32ea135e86bd82d70e57281", "completed", "failure"),
        make_run("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "in_progress"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": runs})
        return httpx.Response(200, json=commits)

    body = get_release_notes(handler)
    assert body["ok"] is True
    items = {item["short_sha"]: item for item in body["items"]}
    assert "5c7ccf6" in items and "58742cf" in items
    assert items["5c7ccf6"]["ci_status"] == "completed"
    assert items["5c7ccf6"]["ci_conclusion"] == "success"
    assert items["58742cf"]["ci_status"] == "completed"
    assert items["58742cf"]["ci_conclusion"] == "failure"
    assert items["1111111"]["ci_status"] is None
    assert items["1111111"]["ci_conclusion"] is None
    assert items["aaaaaaa"]["ci_status"] == "in_progress"
    assert items["aaaaaaa"]["ci_conclusion"] is None


def test_normalize_ci_maps_queued_and_completed() -> None:
    assert releases_api._normalize_ci("queued", None) == ("queued", None)
    assert releases_api._normalize_ci("waiting", None) == ("in_progress", None)
    assert releases_api._normalize_ci("in_progress", None) == ("in_progress", None)
    assert releases_api._normalize_ci("completed", "success") == ("completed", "success")
    assert releases_api._normalize_ci("completed", None) == ("completed", "unknown")
    assert releases_api._normalize_ci("", None) == ("unknown", None)


def test_release_notes_ci_failure_still_returns_commits() -> None:
    commits = [make_commit("abcdef1234567890abcdef1234567890abcdef12", "hello")]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(200, json=commits)

    body = get_release_notes(handler)
    assert body["ok"] is True
    assert body["items"][0]["short_sha"] == "abcdef1"
    assert body["items"][0]["ci_status"] is None


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
