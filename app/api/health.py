"""Health-check route."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.db import config_revision


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "revision": config_revision()}
