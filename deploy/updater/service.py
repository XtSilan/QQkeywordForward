"""Update orchestration: one-shot helper lifecycle + watch/poll/check logic."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from . import config, docker_api, git, versioning
from .state import save_last_run, start_lock, state


class UpdateConflict(RuntimeError):
    """Another update run is already in progress."""


async def start_helper(trigger: str, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Create and start the one-shot update container.

    Running the work outside this container is what makes self-updating safe:
    compose may recreate ``qq-bot-updater`` while the helper keeps going.
    """
    if not config.ENABLED:
        raise RuntimeError("updater is disabled (UPDATER_ENABLED=false)")
    async with start_lock:
        existing = await docker_api.helper_inspect()
        if existing and existing["running"]:
            raise UpdateConflict("an update is already running")
        if existing:
            async with docker_api.docker_client() as client:
                await client.delete(
                    f"/containers/{config.HELPER_NAME}", params={"force": "true", "v": "true"}
                )
        host_path = await docker_api.host_project_path()
        sha_before = ""
        try:
            sha_before = await git.local_sha()
        except Exception:  # noqa: BLE001 - a broken checkout still deserves an attempt
            pass
        # Bind the checkout at the *same* path as on the host. Inside the helper
        # `docker compose up` resolves relative volumes (./:/project) against the
        # helper's filesystem and ships that absolute path to the daemon — if we
        # remapped to /project, the host would later mount the wrong directory
        # and the updater would lose the git checkout.
        body = {
            "Image": config.HELPER_IMAGE,
            "Cmd": ["python", "-u", "/app/update_run.py"],
            "Env": [
                f"PROJECT_DIR={host_path}",
                f"UPDATER_BRANCH={config.BRANCH}",
                f"UPDATER_TRIGGER={trigger}",
                f"UPDATER_FORCE={'1' if force else '0'}",
                f"UPDATER_DRY_RUN={'1' if dry_run else '0'}",
                "PYTHONUNBUFFERED=1",
            ],
            "Labels": {"qq.bot.updater.role": "update-run"},
            "HostConfig": {
                "Binds": [
                    f"{host_path}:{host_path}",
                    f"{config.DOCKER_SOCKET}:{config.DOCKER_SOCKET}",
                ],
            },
        }
        async with docker_api.docker_client() as client:
            response = await client.post(
                "/containers/create", params={"name": config.HELPER_NAME}, json=body
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"helper create failed: {response.status_code} {response.text[:300]}"
                )
            container_id = str(response.json().get("Id") or "")
            started = await client.post(f"/containers/{container_id}/start")
            if started.status_code >= 400:
                raise RuntimeError(
                    f"helper start failed: {started.status_code} {started.text[:300]}"
                )
        state["active"] = {
            "container_id": container_id[:12],
            "trigger": trigger,
            "force": force,
            "dry_run": dry_run,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sha_before": sha_before,
        }
        config.log.info(
            "update started trigger=%s force=%s dry_run=%s sha=%s",
            trigger, force, dry_run, sha_before[:8] or "?",
        )
        return {
            "started": True,
            "trigger": trigger,
            "force": force,
            "dry_run": dry_run,
            "container_id": container_id[:12],
        }


async def finalize_run(active: dict[str, Any], info: dict[str, Any]) -> None:
    logs = await docker_api.helper_logs()
    try:
        sha_after = await git.local_sha()
    except Exception:  # noqa: BLE001
        sha_after = ""
    record = {
        "trigger": active.get("trigger"),
        "container_id": info.get("id"),
        "started_at": active.get("started_at") or info.get("started_at"),
        "finished_at": info.get("finished_at"),
        "finished_epoch": time.time(),
        "exit_code": info.get("exit_code"),
        "ok": info.get("exit_code") == 0,
        "sha_before": active.get("sha_before") or "",
        "sha_after": sha_after,
        "log_tail": "\n".join(logs.splitlines()[-80:]),
    }
    state["last_run"] = record
    state["active"] = None
    save_last_run(record)
    config.log.info(
        "update finished trigger=%s ok=%s exit=%s %s -> %s",
        record["trigger"], record["ok"], record["exit_code"],
        str(record["sha_before"])[:8] or "?", str(sha_after)[:8] or "?",
    )


async def watch_loop() -> None:
    """Track the helper container and record its result when it exits."""
    while True:
        await asyncio.sleep(3)
        try:
            active = state.get("active")
            info = await docker_api.helper_inspect()
            if info is None:
                if active:
                    config.log.warning("helper container disappeared mid-run")
                    state["active"] = None
                continue
            if active is None and info["running"]:
                # adopted after an updater restart
                state["active"] = {
                    "container_id": info["id"],
                    "trigger": "adopted",
                    "started_at": info["started_at"],
                    "sha_before": "",
                }
                config.log.info("adopted in-flight update %s", info["id"])
                active = state["active"]
            if active is not None and not info["running"] and docker_api.finished(info):
                await finalize_run(active, info)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must survive transient errors
            config.log.exception("watch loop error")


async def poll_once() -> None:
    if not (config.ENABLED and config.AUTO_UPDATE and config.POLL_INTERVAL > 0):
        return
    if state.get("active"):
        return
    last = state.get("last_run") or {}
    if last and not last.get("ok"):
        finished = float(last.get("finished_epoch") or 0)
        # Clock skew can put finished_epoch slightly in the future; a negative
        # age must not satisfy `age < BACKOFF` forever or auto-poll never runs.
        age = time.time() - finished
        if finished and 0 <= age < config.FAILURE_BACKOFF:
            return
    # Shared decision path: behind origin, or running an older build than HEAD.
    await check_and_maybe_start("poll", force=False, dry_run=False)


async def poll_loop() -> None:
    await asyncio.sleep(max(0, config.POLL_INITIAL_DELAY))
    while True:
        try:
            await poll_once()
        except UpdateConflict as exc:
            config.log.info("poll skipped: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            config.log.warning("poll error: %s", exc)
        await asyncio.sleep(max(15, config.POLL_INTERVAL))


async def check_and_maybe_start(trigger: str, force: bool, dry_run: bool) -> dict[str, Any]:
    """Shared body of /api/check, /api/webhook and the poll loop.

    An "update" is needed when the checkout is behind origin **or** when the
    running image was built from an older commit than HEAD (develop-on-server
    workflow: after your own push local == remote, but containers still run the
    previous build).
    """
    local = await git.local_sha()
    remote = await git.remote_sha(force=True)
    behind = remote != local
    version, stale = versioning.compute_build_state(
        state.get("last_run"), versioning.read_env_version(), local
    )
    available = behind or stale
    payload: dict[str, Any] = {
        "ok": True,
        "trigger": trigger,
        "local_sha": local,
        "remote_sha": remote,
        "behind_remote": behind,
        "build_version": version,
        "build_stale": stale,
        "update_available": available,
        "started": False,
        "reason": "",
    }
    if state.get("active"):
        payload["reason"] = "update already running"
        return payload
    if not available and not force:
        payload["reason"] = "already up to date"
        return payload
    if not config.ENABLED:
        payload["reason"] = "updater disabled (UPDATER_ENABLED=false)"
        return payload
    if not config.AUTO_UPDATE and trigger in {"poll", "webhook"}:
        payload["reason"] = "auto-update disabled"
        return payload
    if not force and not dry_run:
        # Auto paths never spawn a helper just to watch it abort on local
        # edits; an explicit force=1 still does (and records the refusal).
        dirty = await git.working_tree_dirty()
        if dirty:
            payload["reason"] = "working tree has local changes, auto update skipped"
            return payload
    try:
        # Equal code but stale build needs FORCE inside the helper to rebuild.
        result = await start_helper(
            trigger, force=force or not behind, dry_run=dry_run
        )
    except UpdateConflict as exc:
        payload["reason"] = str(exc)
        return payload
    payload.update(result)
    payload["reason"] = "update started"
    return payload
