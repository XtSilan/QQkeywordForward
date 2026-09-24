"""Shared run state: in-memory dict + persisted last-run record."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from . import config


def load_last_run() -> dict[str, Any] | None:
    try:
        payload = json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def save_last_run(record: dict[str, Any]) -> None:
    try:
        config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = config.STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(config.STATE_FILE)
    except Exception as exc:  # noqa: BLE001 - status persistence is best-effort
        config.log.warning("cannot persist state: %s", exc)


state: dict[str, Any] = {"active": None, "last_run": load_last_run()}
start_lock = asyncio.Lock()
