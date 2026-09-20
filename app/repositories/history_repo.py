"""Data-access functions for keyword hit history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db import row_dict

LIST_COLUMNS = (
    "id, group_id, group_name, sender_id, sender_name, keyword_id, "
    "keyword_text_snapshot, message_text, message_id, hit_at, notify_status"
)

# hit_at is written as an aware UTC isoformat (see app/nonebot_bot.py). Every
# range bound must be formatted identically for string comparison to stay
# chronological, which is what lets the range test use idx_keyword_hits_hit_at.
HIT_AT_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def storage_timestamp(moment: datetime) -> str:
    """Format an instant the way ``hit_at`` is stored."""
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime(HIT_AT_FORMAT)


def _where(
    group_id: str | None,
    keyword_id: int | None,
    since: str | None,
    until: str | None,
) -> tuple[str, list[Any]]:
    """Build only the predicates that are actually in use.

    A parameterised ``(? IS NULL OR group_id=?)`` test cannot be planned into an
    index lookup, so the old version scanned the whole table (and sorted it)
    even when a group *was* filtered. ``hit_at`` bounds are compared as strings:
    every row is written as an aware UTC isoformat, so lexicographic order
    matches chronological order and the comparison stays index-friendly.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if group_id is not None:
        clauses.append("group_id = ?")
        params.append(group_id)
    if keyword_id is not None:
        clauses.append("keyword_id = ?")
        params.append(keyword_id)
    if since is not None:
        clauses.append("hit_at >= ?")
        params.append(since)
    if until is not None:
        clauses.append("hit_at < ?")
        params.append(until)
    return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), params


def list_hits(
    conn,
    group_id: str | None,
    keyword_id: int | None,
    since: str | None,
    until: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    # Ordered by hit_at alone: hit_at is a microsecond UTC instant so it does
    # not tie in practice, and adding `id` to the ORDER BY would force a
    # temporary sort for the per-group listing path.
    where, params = _where(group_id, keyword_id, since, until)
    rows = conn.execute(
        f"SELECT {LIST_COLUMNS} FROM keyword_hits{where} "
        "ORDER BY hit_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) AS count FROM keyword_hits{where}", params
    ).fetchone()["count"]
    return {
        "items": [row_dict(row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }