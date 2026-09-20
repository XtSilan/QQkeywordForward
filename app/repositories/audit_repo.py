"""Data-access for audit log queries (INSERT happens in the HTTP middleware)."""
from __future__ import annotations

from typing import Any

from app.db import row_dict


def list_logs(conn, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, actor, action, resource_type, resource_id, detail_json, status_code, created_at "
        "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [row_dict(row) for row in rows]