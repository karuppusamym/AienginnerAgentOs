"""Open Knowledge Foundation Frictionless Data interchange.

Maps catalog assets to and from Data Package / Table Schema descriptors
(https://datapackage.org). Deliberately an *adapter*: DataAsset stays the
internal model, and descriptors are produced and consumed at the edge so other
tools (frictionless-py, CKAN, Open Data portals, dbt/ingest tooling) can read
DataPilot's catalog and hand curated metadata back.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import DataAsset

PROFILE_VERSION = "https://datapackage.org/profiles/2.0/datapackage.json"
SCHEMA_PROFILE = "https://datapackage.org/profiles/2.0/tableschema.json"
RESOURCE_PROFILE = "https://datapackage.org/profiles/2.0/dataresource.json"

_TYPE_RULES: tuple[tuple[str, str], ...] = (
    (r"bool", "boolean"),
    (r"timestamp|datetime", "datetime"),
    (r"^date$|\bdate\b", "date"),
    (r"^time\b", "time"),
    (r"int|serial|bigint|smallint", "integer"),
    (r"numeric|decimal|float|double|real|number|money", "number"),
    (r"json|struct|record|variant|object", "object"),
    (r"array|list", "array"),
)


def table_schema_type(raw: str | None) -> str:
    lowered = (raw or "").strip().lower()
    for pattern, frictionless_type in _TYPE_RULES:
        if re.search(pattern, lowered):
            return frictionless_type
    return "string"


def resource_name(asset: DataAsset) -> str:
    # Data Package names: lowercase, digits, "-", "_", "." only.
    return re.sub(r"[^a-z0-9._-]+", "_", f"{asset.schema_name}.{asset.table_name}".lower()).strip("_") or asset.id


def asset_resource(asset: DataAsset, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fields = []
    for column in asset.columns or []:
        name = str(column.get("name") or "").strip()
        if not name:
            continue
        field: dict[str, Any] = {"name": name, "type": table_schema_type(column.get("type"))}
        if column.get("business_name"):
            field["title"] = column["business_name"]
        if column.get("description"):
            field["description"] = column["description"]
        if column.get("nullable") is False:
            field["constraints"] = {"required": True}
        if column.get("type"):
            field["datapilot:sourceType"] = str(column["type"])
        fields.append(field)
    resource: dict[str, Any] = {
        "$schema": RESOURCE_PROFILE,
        "name": resource_name(asset),
        "title": asset.table_name,
        "type": "table",
        "schema": {"$schema": SCHEMA_PROFILE, "fields": fields},
        "datapilot:assetId": asset.id,
        "datapilot:relation": f"{asset.schema_name}.{asset.table_name}",
        "datapilot:sensitivity": asset.sensitivity,
        "datapilot:metadataStatus": asset.metadata_status,
    }
    if asset.description:
        resource["description"] = asset.description
    if asset.source_name:
        resource["sources"] = [{"title": asset.source_name}]
    if asset.row_count is not None:
        resource["datapilot:rowCount"] = asset.row_count
    if asset.owner:
        resource["datapilot:owner"] = asset.owner
    if asset.tags:
        resource["datapilot:tags"] = list(asset.tags)
    if rows is not None:
        # Inline data keeps the package self-contained; bounded by the caller.
        resource["data"] = rows
    else:
        # Data lives in the governed store; consumers query it through DataPilot.
        resource["path"] = f"datapilot://{asset.schema_name}/{asset.table_name}"
    return resource


def data_package(name: str, title: str, resources: list[dict[str, Any]], description: str | None = None) -> dict[str, Any]:
    package: dict[str, Any] = {
        "$schema": PROFILE_VERSION,
        "name": re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-") or "datapilot-package",
        "title": title,
        "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "resources": resources,
    }
    if description:
        package["description"] = description
    keywords = sorted({tag for resource in resources for tag in resource.get("datapilot:tags", [])})
    if keywords:
        package["keywords"] = keywords
    return package


def validate_descriptor(descriptor: dict[str, Any]) -> list[str]:
    """Structural checks from the Data Package / Table Schema specs (not a full JSON-Schema validation)."""
    errors: list[str] = []
    resources = descriptor.get("resources")
    if not isinstance(resources, list) or not resources:
        return ["descriptor.resources must be a non-empty array"]
    seen: set[str] = set()
    for index, resource in enumerate(resources):
        where = f"resources[{index}]"
        if not isinstance(resource, dict):
            errors.append(f"{where} must be an object")
            continue
        name = resource.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9._-]+", name):
            errors.append(f"{where}.name must match ^[a-z0-9._-]+$")
        elif name in seen:
            errors.append(f"{where}.name '{name}' is duplicated")
        else:
            seen.add(name)
        if "path" not in resource and "data" not in resource:
            errors.append(f"{where} needs either path or data")
        schema = resource.get("schema")
        if schema is None:
            continue
        fields = schema.get("fields") if isinstance(schema, dict) else None
        if not isinstance(fields, list):
            errors.append(f"{where}.schema.fields must be an array")
            continue
        field_names: set[str] = set()
        for field_index, field in enumerate(fields):
            if not isinstance(field, dict) or not isinstance(field.get("name"), str) or not field["name"]:
                errors.append(f"{where}.schema.fields[{field_index}].name is required")
                continue
            if field["name"] in field_names:
                errors.append(f"{where}.schema.fields[{field_index}].name '{field['name']}' is duplicated")
            field_names.add(field["name"])
    return errors


def metadata_changes(asset: DataAsset, resource: dict[str, Any]) -> dict[str, Any]:
    """Translate a curated resource back into a DataAssetUpdate-shaped patch.

    Only descriptive metadata flows inward (titles, descriptions, tags). Types,
    constraints and physical names are never taken from an external descriptor.
    """
    known = {str(column.get("name")) for column in asset.columns or []}
    column_notes: dict[str, dict[str, str]] = {}
    for field in (resource.get("schema") or {}).get("fields") or []:
        name = field.get("name")
        if name not in known:
            continue
        notes = {}
        if isinstance(field.get("title"), str) and field["title"].strip():
            notes["business_name"] = field["title"].strip()[:200]
        if isinstance(field.get("description"), str) and field["description"].strip():
            notes["description"] = field["description"].strip()[:2_000]
        if notes:
            column_notes[name] = notes
    patch: dict[str, Any] = {}
    if isinstance(resource.get("description"), str) and resource["description"].strip():
        patch["description"] = resource["description"].strip()[:5_000]
    tags = resource.get("datapilot:tags") or resource.get("keywords")
    if isinstance(tags, list) and all(isinstance(tag, str) for tag in tags):
        patch["tags"] = [tag[:80] for tag in tags][:32]
    if column_notes:
        patch["column_notes"] = column_notes
    return patch
