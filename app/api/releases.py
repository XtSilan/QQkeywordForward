"""Release notes: the newest commits of the upstream repo, fetched server-side.

The browser used to call ``api.github.com`` directly, which fails two ways:
unauthenticated GitHub allows only 60 requests/hour per IP (a shared egress IP
exhausts that quickly and returns 403), and some networks cannot reach
``api.github.com`` at all even when ``github.com`` loads. Fetching from the
control plane gives us a dedicated quota, and the short cache keeps several
open consoles down to a single upstream request.

Each entry also carries the short SHA and the GitHub Actions conclusion for
that commit (✓ / ✗ / in-progress) so the bell can show CI status without a
second round-trip from the browser.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from app.api.deps import admin_guard

REPO = "XtSilan/QQkeywordForward"
PAGE_SIZE = 15
TIMEOUT_SECONDS = 8
CACHE_TTL_SECONDS = 60  # short: new pushes should appear in the bell quickly
API_URL = f"https://api.github.com/repos/{REPO}/commits"
RUNS_URL = f"https://api.github.com/repos/{REPO}/actions/runs"

router = APIRouter(prefix="/api", tags=["releases"], dependencies=[Depends(admin_guard)])

_items: list[dict[str, Any]] = []
_cached_at = 0.0


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse(item: Any) -> dict[str, Any] | None:
    """A commit message is "title line + body"; both become one entry."""
    entry = _dict(item)
    sha = str(entry.get("sha") or "")
    commit = _dict(entry.get("commit"))
    message = str(commit.get("message") or "")
    if not sha or not message.strip():
        return None
    lines = message.split("\n")
    return {
        "sha": sha,
        "short_sha": sha[:7],
        "time": str(_dict(commit.get("author")).get("date") or ""),
        "title": lines[0].strip(),
        "body": "\n".join(lines[1:]).strip(),
        # Filled in by _attach_ci; null when Actions has no run for the commit.
        "ci_status": None,
        "ci_conclusion": None,
    }


def _normalize_ci(status: str, conclusion: str | None) -> tuple[str, str | None]:
    """Map a workflow run to a stable (status, conclusion) pair for the UI.

    ``status`` is one of: queued | in_progress | completed | unknown.
    ``conclusion`` is set only when completed (success/failure/...).
    """
    status = (status or "").lower()
    conclusion = (conclusion or "").lower() or None
    if status in {"queued", "in_progress", "waiting", "requested", "pending"}:
        return ("in_progress" if status in {"in_progress", "waiting"} else "queued",
                None)
    if status == "completed":
        return "completed", conclusion or "unknown"
    return "unknown", conclusion


async def _fetch_ci_map(client: httpx.AsyncClient) -> dict[str, tuple[str, str | None]]:
    """head_sha -> (status, conclusion) for the newest run of each SHA.

    One ``actions/runs`` call covers every commit in the page (runs are newest
    first, so the first hit per SHA wins). Failures degrade to an empty map —
    release notes still render without badges.
    """
    try:
        response = await client.get(
            RUNS_URL,
            params={"per_page": 60},
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001 - CI badges are best-effort
        return {}
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        return {}
    ci: dict[str, tuple[str, str | None]] = {}
    for run in runs:
        entry = _dict(run)
        sha = str(entry.get("head_sha") or "")
        if not sha or sha in ci:
            continue  # keep the newest run per SHA
        ci[sha] = _normalize_ci(
            str(entry.get("status") or ""),
            entry.get("conclusion") if isinstance(entry.get("conclusion"), str) else None,
        )
    return ci


def _attach_ci(items: list[dict[str, Any]], ci: dict[str, tuple[str, str | None]]) -> None:
    for item in items:
        pair = ci.get(item["sha"])
        if pair is None:
            item["ci_status"] = None
            item["ci_conclusion"] = None
        else:
            item["ci_status"], item["ci_conclusion"] = pair


@router.get("/release-notes")
async def release_notes() -> dict[str, Any]:
    """Cached newest commits + Actions status.

    An unreachable or rate-limited GitHub never raises: the caller gets
    ``ok=False`` plus whatever was cached, so the UI can say "unavailable"
    instead of silently pretending there are no updates.
    """
    global _items, _cached_at
    now = time.monotonic()
    if _items and now - _cached_at < CACHE_TTL_SECONDS:
        return {"items": _items, "ok": True}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(
                API_URL,
                params={"per_page": PAGE_SIZE},
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            payload = response.json()
            ci = await _fetch_ci_map(client)
    except Exception:
        return {"items": _items, "ok": False}
    entries = [_parse(item) for item in payload] if isinstance(payload, list) else []
    parsed = [entry for entry in entries if entry is not None]
    if parsed:
        _attach_ci(parsed, ci)
        _items = parsed
        _cached_at = now
    return {"items": parsed, "ok": True}
