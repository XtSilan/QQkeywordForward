"""FastAPI surface: status/check/update/webhook routes."""
from __future__ import annotations

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from . import config, docker_api, git, service, signatures, versioning
from .service import UpdateConflict, check_and_maybe_start
from .state import state


@asynccontextmanager
async def lifespan(_: FastAPI):
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config.log.info(
        "updater up project=%s branch=%s enabled=%s auto_update=%s poll=%ss",
        config.PROJECT_DIR, config.BRANCH, config.ENABLED, config.AUTO_UPDATE,
        config.POLL_INTERVAL,
    )
    tasks = [asyncio.create_task(service.watch_loop())]
    if config.ENABLED and config.AUTO_UPDATE and config.POLL_INTERVAL > 0:
        tasks.append(asyncio.create_task(service.poll_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="QQ Bot Updater", version="1.0.0", lifespan=lifespan)


def require_token(request: Request) -> None:
    if not config.UPDATER_TOKEN:
        raise HTTPException(status_code=403, detail="UPDATER_TOKEN is not configured")
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or not hmac.compare_digest(
        authorization[len("Bearer "):], config.UPDATER_TOKEN
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


async def status_payload(check_remote: bool = False) -> dict[str, Any]:
    local = remote = ""
    errors: list[str] = []
    try:
        local = await git.local_sha()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"local: {exc}")
    if check_remote:
        try:
            remote = await git.remote_sha(force=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"remote: {exc}")
    else:
        try:
            remote = await git.remote_sha()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"remote: {exc}")
    helper = await docker_api.helper_inspect()
    version, stale = versioning.compute_build_state(
        state.get("last_run"), versioning.read_env_version(), local
    )
    dirty = await git.working_tree_dirty()
    behind = bool(remote and local and remote != local)
    return {
        "ok": not errors,
        "errors": errors,
        "enabled": config.ENABLED,
        "auto_update": config.AUTO_UPDATE,
        "poll_interval": config.POLL_INTERVAL,
        "branch": config.BRANCH,
        "project_dir": str(config.PROJECT_DIR),
        "local_sha": local,
        "local_short": local[:8],
        "remote_sha": remote,
        "remote_short": remote[:8],
        "behind_remote": behind if remote and local else None,
        "build_version": version,
        "build_stale": stale if local else None,
        "working_tree_dirty": dirty,
        "update_available": (behind or stale) if local else None,
        "helper_running": bool(helper and helper["running"]),
        "helper": helper,
        "active": state.get("active"),
        "last_run": state.get("last_run"),
    }


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "qq-bot-updater"}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return await status_payload(check_remote=False)


@app.post("/api/check")
async def api_check(request: Request) -> dict[str, Any]:
    """Re-check the remote now; starts an update when behind (if auto_update)."""
    require_token(request)
    return await check_and_maybe_start("manual", force=False, dry_run=False)


@app.post("/api/update")
async def api_update(request: Request) -> dict[str, Any]:
    """Manual trigger. ``{"force": true}`` rebuilds even without new commits;
    ``{"dry_run": true}`` only fetches and reports (no pull, no rebuild)."""
    require_token(request)
    try:
        body = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object body required")
    force = bool(body.get("force"))
    dry_run = bool(body.get("dry_run"))
    if force and state.get("active"):
        raise HTTPException(status_code=409, detail="update already running")
    # force=1 rebuilds even when already up to date; dry_run=1 only fetches.
    return await check_and_maybe_start("manual", force=force, dry_run=dry_run)


@app.post("/api/webhook")
async def api_webhook(request: Request) -> dict[str, Any]:
    """CD entrypoint: GitHub Actions (or a native GitHub webhook) push event."""
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    token_header = request.headers.get("x-updater-token", "")
    if config.WEBHOOK_SECRET:
        if not signatures.verify_signature(config.WEBHOOK_SECRET, raw, signature):
            raise HTTPException(status_code=401, detail="invalid signature")
    elif config.UPDATER_TOKEN:
        if not hmac.compare_digest(token_header, config.UPDATER_TOKEN):
            raise HTTPException(status_code=403, detail="invalid updater token")
    else:
        raise HTTPException(
            status_code=503,
            detail="webhook not configured (set UPDATER_WEBHOOK_SECRET or UPDATER_TOKEN)",
        )

    event = request.headers.get("x-github-event", "")
    if event == "ping":
        return {"ok": True, "msg": "pong"}
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object body required")
    ref = str(payload.get("ref") or "")
    if not ref:
        return {"ok": True, "ignored": True, "reason": "payload has no ref"}
    if not signatures.is_target_ref(ref, config.BRANCH):
        return {"ok": True, "ignored": True, "reason": f"{ref} is not the tracked branch"}
    dry_run = bool(payload.get("dry_run"))
    return await check_and_maybe_start("webhook", force=False, dry_run=dry_run)
