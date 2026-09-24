"""Answer "what columns / schema / describe this table" from the catalog, without running SQL.

A structure question is not an analytical one: generating SQL for it either hits
the metadata guard (information_schema is off-limits) or falls back to an
unrelated query. The catalog already holds the answer: columns, types, business
names, descriptions and sensitivity. "This / that / the closest table" resolves
to the table the conversation was just about, across sources.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Connector, ConversationMessage, DataAsset

_STRUCTURE = re.compile(r"\b(columns?|fields?|schema|structure|attributes|data\s*types?|describe|layout|metadata)\b", re.IGNORECASE)
_ANALYTIC = re.compile(r"\b(count|how many|sum|total|average|avg|mean|trend|per|top|max|min|maximum|minimum|distribution|compare|growth|rate|null|distinct|values?)\b", re.IGNORECASE)
_REFERENCE = re.compile(r"\b(this|that|these|those|same|previous|above|closest|it|its|the table|the dataset)\b", re.IGNORECASE)


def is_structure_question(question: str) -> bool:
    return bool(_STRUCTURE.search(question)) and not _ANALYTIC.search(question)


def _relation(asset: DataAsset) -> str:
    return f"{asset.schema_name}.{asset.table_name}".lower()


def _mentioned(text: str, assets: list[DataAsset]) -> list[DataAsset]:
    lowered = (text or "").lower()
    return [asset for asset in assets if _relation(asset) in lowered]


def _prefer(candidates: list[DataAsset], connector_id: str | None) -> DataAsset | None:
    if not candidates:
        return None
    return next((asset for asset in candidates if asset.connector_id == connector_id), candidates[0])


def resolve_asset(db: Session, project_id: str, question: str, prior: list[ConversationMessage], connector_id: str | None) -> tuple[DataAsset | None, str]:
    assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project_id)).all()
    explicit = _mentioned(question, assets)
    if explicit:
        return _prefer(explicit, connector_id), "named in the question"
    if _REFERENCE.search(question) or len(question.split()) <= 8:
        # Newest first: what the user named, then what the previous answer was about.
        for message in reversed(prior):
            if message.role == "user":
                found = _mentioned(message.content, assets)
                if found:
                    return _prefer(found, connector_id), "from earlier in this conversation"
            else:
                for item in (message.structured or {}).get("sources") or []:
                    if isinstance(item, dict) and item.get("asset"):
                        source_id = (item.get("source") or {}).get("id")
                        found = [asset for asset in assets if _relation(asset) == str(item["asset"]).lower()]
                        match = next((asset for asset in found if asset.connector_id == source_id), None) or _prefer(found, connector_id)
                        if match is not None:
                            return match, "the table the previous answer used"
    from .grounding import grounding_context

    scope = {asset.id for asset in assets if asset.connector_id == connector_id} if connector_id else None
    matches = grounding_context(db, project_id, question, limit=3, allowed_asset_ids=scope)["catalog_matches"]
    if matches:
        asset = next((asset for asset in assets if asset.id == matches[0]["asset_id"]), None)
        if asset is not None:
            return asset, "closest catalog match"
    return None, ""


def catalog_structure_answer(db: Session, project_id: str, question: str, prior: list[ConversationMessage], connector_id: str | None) -> dict[str, Any] | None:
    """Structured answer for a structure question, or None when this isn't one or no table resolves."""
    if not is_structure_question(question):
        return None
    asset, how = resolve_asset(db, project_id, question, prior, connector_id)
    if asset is None:
        return None
    connector = db.get(Connector, asset.connector_id) if asset.connector_id else None
    source_name = connector.name if connector else asset.source_name
    columns = list(asset.columns or [])
    rows = [
        {
            "column": str(column.get("name", "")),
            "type": str(column.get("type", "") or column.get("inferred_type", "")),
            "business_name": column.get("business_name") or "",
            "description": column.get("description") or "",
            "nullable": column.get("nullable", True),
            "sensitivity": column.get("sensitivity") or ("pii" if column.get("pii_category") else ""),
        }
        for column in columns
    ]
    relation = f"{asset.schema_name}.{asset.table_name}"
    listed = ", ".join(f"{row['column']} ({row['type']})" if row["type"] else row["column"] for row in rows[:25])
    extra = f" and {len(rows) - 25} more" if len(rows) > 25 else ""
    pii = [row["column"] for row in rows if row["sensitivity"] == "pii"]
    text = (
        f"`{relation}` in {source_name} has {len(rows)} column{'s' if len(rows) != 1 else ''}: {listed}{extra}."
        + (f" {asset.description.strip()}" if (asset.description or "").strip() else "")
        + (f" Rows: about {asset.row_count:,}." if asset.row_count else "")
        + (f" Personal data columns (masked in results): {', '.join(pii)}." if pii else "")
        + f" Answered from catalog metadata ({how}); no data was queried."
    )
    source = {
        "id": connector.id if connector else None,
        "name": source_name,
        "database": source_name,
        "connector_type": connector.connector_type if connector else "local_files",
        "dialect": "postgres",
        "connection_mode": getattr(connector, "connection_mode", "direct") if connector else "direct",
    }
    return {
        "answer": text,
        "relation": relation,
        "asset_id": asset.id,
        "resolved_by": how,
        "source": source,
        "execution": {"columns": ["column", "type", "business_name", "description", "nullable", "sensitivity"], "rows": rows, "row_count": len(rows), "truncated": False, "limit": len(rows), "duration_ms": 0},
    }
