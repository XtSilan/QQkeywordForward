"""Env-driven configuration for the updater service (read once at import)."""
from __future__ import annotations

import logging
import os
from pathlib import Path


def _truthy(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


PROJECT_DIR = Path(os.environ.get("PROJECT_DIR", "/project")).resolve()
BRANCH = (os.environ.get("UPDATER_BRANCH") or "master").strip()
if BRANCH.startswith("refs/heads/"):
    BRANCH = BRANCH[len("refs/heads/"):]
DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
UPDATER_TOKEN = (os.environ.get("UPDATER_TOKEN") or "").strip()
WEBHOOK_SECRET = (os.environ.get("UPDATER_WEBHOOK_SECRET") or "").strip()
POLL_INTERVAL = int(os.environ.get("UPDATER_POLL_INTERVAL") or "300")
POLL_INITIAL_DELAY = int(os.environ.get("UPDATER_POLL_INITIAL_DELAY") or "30")
AUTO_UPDATE = _truthy(os.environ.get("UPDATER_AUTO_UPDATE"), True)
ENABLED = _truthy(os.environ.get("UPDATER_ENABLED"), True)
HELPER_NAME = os.environ.get("UPDATER_HELPER_NAME", "qq-bot-updater-run")
HELPER_IMAGE = os.environ.get("UPDATER_HELPER_IMAGE", "qq-bot-updater:local")
BIND_FALLBACK = (os.environ.get("UPDATER_BIND_PATH") or "").strip()
STATE_FILE = Path(
    os.environ.get("UPDATER_STATE_FILE")
    or str(PROJECT_DIR / "data" / "updater" / "state.json")
)

REMOTE_CACHE_TTL = 10.0   # seconds between ls-remote calls
FAILURE_BACKOFF = 900.0   # pause auto-poll after a failed update
GIT_TIMEOUT = 30.0

log = logging.getLogger("updater")
