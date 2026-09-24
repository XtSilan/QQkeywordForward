"""Health-check route."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.db import config_revision
from app.settings import get_settings


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "ok": True,
        "revision": config_revision(),
        # build metadata baked in at image build time (see Dockerfile ARG)
        "version": settings.app_version,
        "build_time": settings.app_build_time,
    }
