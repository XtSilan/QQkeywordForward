"""Build-version parsing and staleness decision (pure helpers)."""
from __future__ import annotations

from typing import Any

from . import config


def parse_app_version(env_text: str) -> str:
    """APP_VERSION value from a .env.prod style document."""
    for line in env_text.splitlines():
        line = line.strip()
        if line.startswith("APP_VERSION="):
            return line.split("=", 1)[1].strip()
    return ""


def read_env_version() -> str:
    try:
        return parse_app_version(
            (config.PROJECT_DIR / ".env.prod").read_text(encoding="utf-8")
        )
    except Exception:  # noqa: BLE001
        return ""


def compute_build_state(
    last_run: dict[str, Any] | None,
    env_version: str,
    local_sha: str,
) -> tuple[str, bool]:
    """(version to display, is the running build older than local HEAD).

    A deploy is not only "remote has new commits": when you develop on the
    server itself, pushing makes local == remote while the containers still
    run an older image. So a build whose recorded SHA differs from HEAD is
    stale too, and triggers a rebuild-only update. The authoritative source is
    the last successful helper run; .env.prod's APP_VERSION covers builds that
    happened before the updater existed.
    """
    if not local_sha:
        return env_version or "dev", False
    if last_run and last_run.get("ok") and last_run.get("sha_after"):
        built = str(last_run["sha_after"])
        return built[:8], built[:8] != local_sha[:8]
    if env_version:
        if env_version in {"dev", "dev-local"}:
            return env_version, True
        return env_version, env_version[:8] != local_sha[:8]
    return "dev", True
