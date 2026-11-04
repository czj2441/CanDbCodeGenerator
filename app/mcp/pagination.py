"""共享分页/过滤 — 列表类工具统一响应约定（Task 7 创建，Task 8/9/11 复用）。

响应信封：{"total", "count", "offset", "items", "has_more", "next_offset"}；
limit 默认 50、上限 200（超限截断）。
"""
from __future__ import annotations

from typing import Any, Iterable

# limit 默认值与上限（全局约定：limit 默认 50、上限 200）
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def paginate(
    items: Iterable[Any],
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    filter: str | None = None,
    filter_fields: tuple[str, ...] = (),
) -> dict:
    """过滤 + 分页，返回统一信封。

    - filter：大小写不敏感子串，命中 filter_fields 任一字段（str 化后）即保留；
      给了 filter 必须给 filter_fields（否则 ValueError）。
    - total 为过滤后总数；count 为本页条数；next_offset 无下一页时为 None。
    - limit 截断到 [0, MAX_LIMIT]（超限截断），offset 截断到 >= 0。
    """
    if filter and not filter_fields:
        raise ValueError("filter_fields 不能为空")
    if filter:
        needle = str(filter).lower()
        items = [
            item
            for item in items
            if any(needle in str(item.get(field, "")).lower() for field in filter_fields)
        ]
    items = list(items)
    total = len(items)
    limit = max(0, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    page = items[offset:offset + limit]
    count = len(page)
    has_more = offset + count < total
    return {
        "total": total,
        "count": count,
        "offset": offset,
        "items": page,
        "has_more": has_more,
        "next_offset": offset + count if has_more else None,
    }
