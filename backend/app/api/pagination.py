"""Pagination helpers shared by list endpoints."""
from __future__ import annotations

import math

from fastapi import Query

from app.schemas.common import Page


def page_params(
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
) -> tuple[int, int]:
    return page, page_size


def make_page(items: list, page: int, page_size: int, total: int) -> Page:
    return Page(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        pages=math.ceil(total / page_size) if page_size else 0,
    )
