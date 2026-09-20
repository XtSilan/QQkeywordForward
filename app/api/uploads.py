"""Image upload route."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import admin_guard
from app.settings import Settings, get_settings


router = APIRouter(prefix="/api", tags=["uploads"], dependencies=[Depends(admin_guard)])


@router.post("/uploads/image")
async def upload_image(file: UploadFile = File(...), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
    suffix = allowed.get(file.content_type or "")
    if not suffix:
        raise HTTPException(status_code=415, detail="只支持 JPG、PNG、GIF、WEBP 图片")
    limit = settings.max_upload_size_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {settings.max_upload_size_mb}MB")
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    (upload_dir / filename).write_bytes(data)
    url = settings.public_base_url.rstrip("/") + "/media/" + filename
    return {"url": url, "segment": {"type": "image", "data": {"file": url}}}