from typing import Any

from pydantic import BaseModel, Field


class BroadcastTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    group_ids: list[str] = Field(min_length=1)
    message: list[dict[str, Any]] = Field(min_length=1)
    interval_seconds: int = Field(default=12, ge=5, le=60)
    group_cooldown_seconds: int = Field(default=0, ge=0, le=86400)


class BroadcastTaskPatch(BaseModel):
    interval_seconds: int | None = Field(default=None, ge=5)
