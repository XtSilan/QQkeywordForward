from typing import Any

from pydantic import BaseModel, Field

# Mirrors the CHECK constraint in migrations/005_broadcast_interval_floor.sql.
MIN_INTERVAL_SECONDS = 1
MAX_INTERVAL_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 2

# Round gap for looping tasks (migrations/009_broadcast_loop.sql). Capped so a
# typo cannot park a task for months, and floored because a round already takes
# total_count * interval_seconds to deliver.
MIN_LOOP_INTERVAL_SECONDS = 5
MAX_LOOP_INTERVAL_SECONDS = 86400
DEFAULT_LOOP_INTERVAL_SECONDS = 60
MAX_LOOP_TOTAL = 50


class BroadcastTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    group_ids: list[str] = Field(min_length=1)
    message: list[dict[str, Any]] = Field(min_length=1)
    interval_seconds: int = Field(
        default=DEFAULT_INTERVAL_SECONDS, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    group_cooldown_seconds: int = Field(default=0, ge=0, le=86400)
    # 0 (the default) sends the schedule once; 1 is equivalent to 0.
    loop_total: int = Field(default=0, ge=0, le=MAX_LOOP_TOTAL)
    loop_interval_seconds: int = Field(
        default=DEFAULT_LOOP_INTERVAL_SECONDS,
        ge=MIN_LOOP_INTERVAL_SECONDS,
        le=MAX_LOOP_INTERVAL_SECONDS,
    )


class BroadcastResumePayload(BaseModel):
    """Optional new group delay applied while resuming a paused task."""

    interval_seconds: int | None = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )


class BroadcastIntervalsPayload(BaseModel):
    """Retune a task's pacing without touching its schedule.

    ``loop_interval_seconds`` only decides when the *next* round starts, so it is
    safe to change at any time. ``interval_seconds`` re-spaces the groups that
    are still queued, so it stays restricted to a paused task — the same rule
    the resume route already applies.
    """

    interval_seconds: int | None = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    loop_interval_seconds: int | None = Field(
        default=None, ge=MIN_LOOP_INTERVAL_SECONDS, le=MAX_LOOP_INTERVAL_SECONDS
    )