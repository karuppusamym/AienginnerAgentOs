"""Offset pagination shared by list endpoints.

Contract: ``?limit=`` (1..200) and ``?offset=`` (>= 0). Responses stay plain JSON
arrays; ``X-Total-Count`` carries the filtered total and ``X-Has-More`` whether
another page exists. Without ``limit`` an endpoint keeps its legacy (unpaged or
legacy-capped) behaviour so existing callers that expect the full list keep
working; the headers are sent either way.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi import Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 200
PAGINATION_HEADERS = ["X-Total-Count", "X-Has-More"]

T = TypeVar("T")


@dataclass(frozen=True)
class Page:
    limit: int | None
    offset: int


def page_params(
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> Page:
    return Page(limit=limit, offset=offset)


def _set_headers(response: Response, total: int, offset: int, returned: int) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Has-More"] = "true" if offset + returned < total else "false"


def paginate_query(db: Session, statement: Select, response: Response, page: Page, default_limit: int | None = None) -> Sequence[Any]:
    """Runs ``statement`` (ORM entity select) for one page and sets the pagination headers."""
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    limit = page.limit or default_limit
    if limit is not None:
        statement = statement.limit(limit)
    if page.offset:
        statement = statement.offset(page.offset)
    rows = db.scalars(statement).all()
    _set_headers(response, total, page.offset, len(rows))
    return rows


def paginate_items(items: Sequence[T], response: Response, page: Page, default_limit: int | None = None) -> list[T]:
    """Pages an already-materialised list (endpoints whose filters are computed in Python)."""
    limit = page.limit or default_limit
    end = None if limit is None else page.offset + limit
    chunk = list(items[page.offset:end])
    _set_headers(response, len(items), page.offset, len(chunk))
    return chunk


def _facet_label(value: Any) -> str:
    return (str(value).strip() if value is not None else "") or "Unassigned"


def facet_counts(values: Iterable[Any]) -> list[dict[str, Any]]:
    """[{"value", "count"}] sorted by count desc, then value; blanks become "Unassigned"."""
    return grouped_counts((value, 1) for value in values)


def grouped_counts(rows: Iterable[tuple[Any, int]]) -> list[dict[str, Any]]:
    """Like ``facet_counts`` for (value, count) rows from a SQL GROUP BY."""
    counts: Counter[str] = Counter()
    for value, count in rows:
        counts[_facet_label(value)] += int(count or 0)
    return [{"value": value, "count": count} for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))]


def escape_like(value: str) -> str:
    """Escapes LIKE wildcards; use with ``escape="\\\\"``."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains(value: str | None) -> str:
    """LIKE pattern for a case-insensitive substring match against ``func.lower(column)``."""
    return f"%{escape_like((value or '').strip().lower())}%"
