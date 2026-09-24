"""Best-effort PostgreSQL-to-SQLite compatibility for the no-Docker dev path.

The API falls back to SQLite when DATABASE_URL is unset, but every SQL
generator (deterministic and model-backed) targets PostgreSQL for the local
workspace. Without this layer the most common generated statements, such as
``DATE_TRUNC('month', ...)`` or ``CURRENT_TIMESTAMP - INTERVAL '12 months'``,
fail with syntax errors, so the local quick start could never show results.
This is not a general transpiler; production uses PostgreSQL.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

_UNITS = {
    "year": "years", "years": "years",
    "month": "months", "months": "months", "mon": "months", "mons": "months",
    "week": "days", "weeks": "days",
    "day": "days", "days": "days",
    "hour": "hours", "hours": "hours",
    "minute": "minutes", "minutes": "minutes", "min": "minutes", "mins": "minutes",
    "second": "seconds", "seconds": "seconds", "sec": "seconds", "secs": "seconds",
}
_NOW = r"(?:CURRENT_TIMESTAMP|CURRENT_DATE|NOW\(\s*\))"
_INTERVAL_FROM_NOW = re.compile(rf"{_NOW}\s*([-+])\s*INTERVAL\s*'\s*(\d+)\s*([a-z]+)\s*'", re.IGNORECASE)
_CAST = re.compile(r"((?:\"[^\"]+\"|\b[\w]+)(?:\.(?:\"[^\"]+\"|[\w]+))?|\))::\s*([a-z_]+(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)", re.IGNORECASE)
_CAST_TYPES = {"date": "TEXT", "timestamp": "TEXT", "timestamptz": "TEXT", "text": "TEXT", "varchar": "TEXT",
               "int": "INTEGER", "integer": "INTEGER", "bigint": "INTEGER", "numeric": "REAL", "decimal": "REAL",
               "float": "REAL", "double": "REAL", "real": "REAL", "boolean": "INTEGER"}


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


def _date_trunc(unit: str, value: Any) -> str | None:
    moment = _parse(value)
    if moment is None:
        return None
    unit = (unit or "").lower()
    if unit == "year":
        moment = moment.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    elif unit == "quarter":
        moment = moment.replace(month=(moment.month - 1) // 3 * 3 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    elif unit == "month":
        moment = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif unit == "week":
        from datetime import timedelta

        moment = (moment - timedelta(days=moment.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif unit == "day":
        moment = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    elif unit == "hour":
        moment = moment.replace(minute=0, second=0, microsecond=0)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def register_postgres_functions(connection: sqlite3.Connection) -> None:
    connection.create_function("date_trunc", 2, _date_trunc, deterministic=True)
    connection.create_function("now", 0, lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))


def _interval(match: re.Match[str]) -> str:
    sign, amount, unit = match.group(1), int(match.group(2)), match.group(3).lower()
    modifier_unit = _UNITS.get(unit)
    if modifier_unit is None:
        return match.group(0)
    if unit.startswith("week"):
        amount *= 7
    return f"datetime('now', '{'-' if sign == '-' else '+'}{amount} {modifier_unit}')"


def sqlite_compatible_sql(sql: str, main_tables: set[str]) -> str:
    """Rewrite common PostgreSQL syntax and drop schemas for tables stored in SQLite's main database."""
    rewritten = _INTERVAL_FROM_NOW.sub(_interval, sql)
    rewritten = _CAST.sub(lambda m: f"CAST({m.group(1)} AS {_CAST_TYPES.get(m.group(2).split('(')[0].strip().lower(), 'TEXT')})", rewritten)
    rewritten = re.sub(r"\bILIKE\b", "LIKE", rewritten, flags=re.IGNORECASE)
    lowered = {table.lower() for table in main_tables}

    def unqualify(match: re.Match[str]) -> str:
        table = match.group(2).strip('"')
        return f'"{table}"' if table.lower() in lowered else match.group(0)

    # SQLite has no core/staging schemas; the demo and staged tables live in "main".
    rewritten = re.sub(r'(?<![\w."])("?[A-Za-z_]\w*"?)\s*\.\s*("?[A-Za-z_]\w*"?)(?=\s|$|,|\)|;)', lambda m: unqualify(m) if m.group(1).strip('"').lower() in {"core", "staging", "public", "main", "activity"} else m.group(0), rewritten)
    return rewritten
