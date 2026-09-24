"""Uvicorn entrypoint: the updater implementation lives in the ``updater``
package (config/git/docker_api/state/versioning/signatures/service/api);
this file only wires the ASGI app to a server so ``python app.py`` and
``uvicorn app:app`` keep working.

Trigger chain (see updater.service)::

    git push -> GitHub Actions (tests pass) -> POST /api/webhook
                                               |
    poll loop (git ls-remote 兜底)  -----------+--> spawn throwaway helper
                                               |   container (qq-bot-updater-run)
                                               |     -> git pull --ff-only
                                               |     -> docker compose build && up -d
                                               v
                                     updater 自身可被 compose 安全重建
"""
from __future__ import annotations

import os

import uvicorn

from updater.api import app  # noqa: F401 - re-exported as the ASGI app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("UPDATER_HOST", "0.0.0.0"),
        port=int(os.environ.get("UPDATER_PORT", "18081")),
        log_level="info",
    )
