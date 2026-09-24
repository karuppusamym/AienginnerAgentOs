"""Pick a chart that fits the shape of a result set.

Rules (first match wins), with the other valid types offered as alternatives:
- 1 row of numbers                      → kpi
- a temporal column + a number          → line (one line per category when a second, low-cardinality text column exists)
- two text columns + a number           → grouped_bar (stacked_bar as alternative)
- one text column + one number          → bar; pie is recommended instead for a small part-of-a-whole
                                          (≤ 8 non-negative slices and a share/percent/count-like measure)
- two or more numbers and no text       → scatter
- anything else                         → table
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

_TEMPORAL_NAME = re.compile(r"(date|day|week|month|year|quarter|time|period|_at$|_on$)", re.IGNORECASE)
_SHARE_NAME = re.compile(r"(share|pct|percent|percentage|ratio|rate|proportion|fraction)", re.IGNORECASE)
_COUNT_NAME = re.compile(r"(count|total|sum|number|num_|qty|quantity|accounts|customers|orders|rows)", re.IGNORECASE)
_MONEY_NAME = re.compile(r"(amount|revenue|balance|price|cost|spend|value_usd|sales)", re.IGNORECASE)
_ID_NAME = re.compile(r"(^id$|_id$|^key$|_key$)", re.IGNORECASE)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _looks_temporal(column: str, values: list[Any]) -> bool:
    if _TEMPORAL_NAME.search(column):
        return True
    sample = [value for value in values if isinstance(value, str)][:5]
    if not sample:
        return False
    for value in sample:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00")[:26])
        except ValueError:
            return False
    return True


def _unit(column: str, values: list[float]) -> str:
    if _SHARE_NAME.search(column):
        return "fraction" if values and max(values) <= 1.0 else "percent"
    if _MONEY_NAME.search(column):
        return "currency"
    if _COUNT_NAME.search(column) and all(float(value).is_integer() for value in values):
        return "count"
    return "number"


def infer_chart(question: str, execution: dict[str, Any] | None) -> dict[str, Any]:
    title = question[:120]
    if not execution or execution.get("error") or not execution.get("rows"):
        return {"type": "table", "title": title, "data": [], "alternatives": ["table"], "reason": "no rows to chart"}
    rows = json.loads(json.dumps(execution["rows"][:500], default=str))
    columns = list(execution.get("columns") or (rows[0].keys() if rows else []))
    values = {column: [row.get(column) for row in rows] for column in columns}
    numeric = [c for c in columns if values[c] and all(v is None or _is_number(v) for v in values[c]) and any(_is_number(v) for v in values[c]) and not _ID_NAME.search(c)]
    temporal = [c for c in columns if c not in numeric and _looks_temporal(c, values[c])]
    text = [c for c in columns if c not in numeric and c not in temporal]
    units = {c: _unit(c, [float(v) for v in values[c] if _is_number(v)]) for c in numeric}
    base = {"title": title, "data": rows[:200], "units": units, "measures": numeric}

    def distinct(column: str) -> int:
        return len({str(v) for v in values[column]})

    if len(rows) == 1 and numeric:
        return {**base, "type": "kpi", "y": numeric[0], "alternatives": ["kpi", "table"], "reason": "a single row of numbers"}
    if temporal and numeric:
        series = next((c for c in text if 1 < distinct(c) <= 8), None)
        alternatives = ["line", "bar", "table"] if not series else ["line", "stacked_bar", "grouped_bar", "table"]
        return {**base, "type": "line", "x": temporal[0], "y": numeric[0], "series": series, "alternatives": alternatives,
                "reason": f"{temporal[0]} is a time axis" + (f", one line per {series}" if series else "")}
    if len(text) >= 2 and numeric and distinct(text[1]) <= 12:
        return {**base, "type": "grouped_bar", "x": text[0], "series": text[1], "y": numeric[0],
                "alternatives": ["grouped_bar", "stacked_bar", "table"], "reason": f"{numeric[0]} by {text[0]} and {text[1]}"}
    if text and numeric:
        measure = numeric[-1] if _SHARE_NAME.search(numeric[-1]) else numeric[0]
        slices = distinct(text[0])
        part_of_whole = slices <= 8 and all((v or 0) >= 0 for v in values[measure]) and (_SHARE_NAME.search(measure) or units[measure] == "count")
        alternatives = ["pie", "bar", "table"] if part_of_whole else ["bar", "table"]
        chart_type = "pie" if part_of_whole and (_SHARE_NAME.search(measure) or slices <= 5) else "bar"
        if chart_type == "bar" and part_of_whole:
            alternatives = ["bar", "pie", "table"]
        return {**base, "type": chart_type, "x": text[0], "y": measure, "alternatives": alternatives,
                "reason": f"{slices} categories of {measure}" + (" (parts of a whole)" if part_of_whole else "")}
    if len(numeric) >= 2 and not text:
        return {**base, "type": "scatter", "x": numeric[0], "y": numeric[1], "alternatives": ["scatter", "table"], "reason": f"{numeric[1]} against {numeric[0]}"}
    return {**base, "type": "table", "alternatives": ["table"], "reason": "no numeric measure to plot"}


def infer_column_types(execution: dict[str, Any] | None) -> list[dict[str, str]]:
    """Column types from sampled values: numeric, timestamp or text (used when publishing to Superset)."""
    if not execution:
        return []
    rows = execution.get("rows") or []
    output = []
    for column in execution.get("columns") or []:
        values = [row.get(column) for row in rows if row.get(column) is not None]
        if values and all(_is_number(v) for v in values) and not _ID_NAME.search(column):
            kind = "numeric"
        elif values and _looks_temporal(column, values):
            kind = "timestamp"
        else:
            kind = "text"
        output.append({"name": column, "type": kind})
    return output
