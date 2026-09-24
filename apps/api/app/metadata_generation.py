"""LLM-suggested descriptions for catalog tables/columns.

Used both when a table is first discovered (connector scan, file ingest —
callers only apply the suggestion if nothing has been reviewed yet) and from
an explicit "Generate with AI" action on an already-catalogued dataset.
Never sends sample row data to the model: a description only needs
schema/column names and types, and sample values could contain PII.
"""
from __future__ import annotations

import json
import re

from .model_runtime import generate_text
from .models import ModelProvider

_DESCRIPTION_MAX = 5_000
_BUSINESS_NAME_MAX = 200
_COLUMN_DESCRIPTION_MAX = 2_000

# Prefixes every hardcoded placeholder description starts with (connector scan,
# file ingest, mapped staging). Anything else is either blank or something a
# human actually typed, and must never be silently overwritten.
_PLACEHOLDER_PREFIXES = ("Discovered from ", "Ingested from ", "Mapped ")


def is_unreviewed_description(description: str | None) -> bool:
    text = (description or "").strip()
    return not text or text.startswith(_PLACEHOLDER_PREFIXES)

_SYSTEM_PROMPT = (
    "You write short, factual data-catalog descriptions. Return JSON only, no Markdown, "
    'matching exactly: {"description": string, "columns": {"<exact column name>": '
    '{"business_name": string, "description": string}}}. Base your answer only on the '
    "table name and the listed column names/types. Do not invent business meaning you "
    "cannot reasonably infer from those names, and do not include columns that are not "
    "in the provided list."
)


def _user_prompt(schema_name: str, table_name: str, columns: list[dict]) -> str:
    column_lines = "\n".join(
        f"- {column.get('name', '')} ({column.get('type', 'unknown')}"
        f"{', nullable' if column.get('nullable', True) else ', required'})"
        for column in columns
    )
    return f"Table: {schema_name}.{table_name}\nColumns:\n{column_lines or '(no columns)'}"


def suggest_dataset_metadata(
    provider: ModelProvider,
    schema_name: str,
    table_name: str,
    columns: list[dict],
    *,
    governance_business_id: str,
    governance_user_id: str | None = None,
) -> dict | None:
    """Return `{"description": str, "columns": {name: {business_name, description}}}` or None.

    Never raises: any failure (empty/unusable provider response, malformed JSON,
    unexpected shape) results in None so callers can fall back to leaving
    whatever description already exists.
    """
    try:
        generated = generate_text(
            provider,
            _SYSTEM_PROMPT,
            _user_prompt(schema_name, table_name, columns),
            900,
            governance_feature="metadata_generation",
            governance_business_id=governance_business_id,
            governance_user_id=governance_user_id,
        )
        content = generated.content.strip()
        if not content:
            return None
        parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I))
        description = parsed.get("description")
        if not isinstance(description, str) or not description.strip():
            return None
        known_names = {str(column.get("name", "")) for column in columns}
        raw_columns = parsed.get("columns")
        column_notes: dict[str, dict[str, str]] = {}
        if isinstance(raw_columns, dict):
            for name, notes in raw_columns.items():
                if name not in known_names or not isinstance(notes, dict):
                    continue
                entry = {}
                business_name = notes.get("business_name")
                if isinstance(business_name, str) and business_name.strip():
                    entry["business_name"] = business_name.strip()[:_BUSINESS_NAME_MAX]
                col_description = notes.get("description")
                if isinstance(col_description, str) and col_description.strip():
                    entry["description"] = col_description.strip()[:_COLUMN_DESCRIPTION_MAX]
                if entry:
                    column_notes[name] = entry
        return {"description": description.strip()[:_DESCRIPTION_MAX], "columns": column_notes}
    except Exception:
        return None
