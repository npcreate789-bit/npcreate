"""Pagination + filter helpers for admin list endpoints.

Shape returned by all paginated list endpoints:

    {"items": [...], "total": N, "limit": L, "offset": O, "has_more": bool}

`limit` is clamped to [1, MAX_LIMIT] and `offset` to >= 0 to protect the DB
from accidental large scans.
"""
from __future__ import annotations

from typing import Any

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_limit(limit: int | None, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    if limit is None:
        return default
    if limit < 1:
        return 1
    if limit > maximum:
        return maximum
    return int(limit)


def clamp_offset(offset: int | None) -> int:
    if offset is None or offset < 0:
        return 0
    return int(offset)


def paginated(items: list[dict[str, Any]], *, total: int, limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": items,
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
        "has_more": offset + len(items) < total,
    }


def like_escape(value: str) -> str:
    """Escape % and _ so the user's q is treated as literal text in LIKE."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
