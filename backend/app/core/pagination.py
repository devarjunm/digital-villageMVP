"""Uniform pagination helpers used by every list endpoint."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")

MAX_PAGE_SIZE = 100


@dataclass(slots=True)
class PageParams:
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size

    def as_dict(self) -> dict[str, int]:
        return {"page": self.page, "page_size": self.page_size}


def page_params(
    page: int = Query(1, ge=1, le=10_000, description="1-based page number"),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE, description="Items per page (max 100)"),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool


def paginate(items: Sequence[Any], params: PageParams, total: int) -> dict[str, Any]:
    total_pages = max(1, (total + params.page_size - 1) // params.page_size) if total else 0
    return {
        "items": list(items),
        "page": params.page,
        "page_size": params.page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": params.page * params.page_size < total,
    }


def count_query(db: Session, stmt: Select[Any]) -> int:
    """COUNT(*) for a SELECT, without loading rows."""
    subq = stmt.order_by(None).options().subquery()
    return int(db.execute(select(func.count()).select_from(subq)).scalar_one())
