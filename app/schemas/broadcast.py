from typing import Any

from pydantic import BaseModel, Field

# Mirrors the CHECK constraint in migrations/005_broadcast_interval_floor.sql.
MIN_INTERVAL_SECONDS = 1
MAX_INTERVAL_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 2


class BroadcastTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    group_ids: list[str] = Field(min_length=1)
    message: list[dict[str, Any]] = Field(min_length=1)
    interval_seconds: int = Field(
        default=DEFAULT_INTERVAL_SECONDS, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    group_cooldown_seconds: int = Field(default=0, ge=0, le=86400)


class BroadcastResumePayload(BaseModel):
    """Optional new group delay applied while resuming a paused task."""

    interval_seconds: int | None = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )