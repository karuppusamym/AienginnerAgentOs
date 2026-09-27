"""Connector contract validation and catalog/extraction column helpers."""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from ..models import Connector, DataAsset
from ..schemas import ConnectorCreate, ConnectorUpdate
from ..staging import safe_identifier
from .sql_service import _json_schema_type


def _validate_connector_contract(payload: ConnectorCreate | ConnectorUpdate) -> None:
    if payload.connection_mode == "mcp":
        if payload.connector_type == "local_files":
            raise HTTPException(status_code=400, detail="Local files do not support MCP connection mode")
        try:
            endpoint = httpx.URL(payload.mcp_server_url or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail="A valid MCP server URL is required") from exc
        if endpoint.scheme not in {"http", "https"} or not endpoint.host:
            raise HTTPException(status_code=400, detail="MCP connection mode requires an http(s) server URL")
        if endpoint.userinfo:
            raise HTTPException(status_code=400, detail="MCP credentials must use an env: secret reference, not the URL")
    elif payload.mcp_server_url:
        raise HTTPException(status_code=400, detail="mcp_server_url is only valid in MCP connection mode")


def dataset_category(asset: DataAsset, connector: Connector | None) -> str:
    if asset.asset_type == "staged_file":
        return "Imported file"
    if asset.asset_type == "view":
        return "Curated view"
    if connector:
        return "External source"
    if any(tag.lower() in {"pii_candidate", "sensitive"} for tag in asset.tags):
        return "Sensitive catalog"
    return "Catalog"


def external_extraction_columns(asset: DataAsset) -> list[dict[str, Any]]:
    return [
        {
            "source_name": str(column.get("name")),
            "target_name": safe_identifier(str(column.get("name")), "column"),
            "target_type": _json_schema_type(column),
            "nullable": bool(column.get("nullable", True)),
        }
        for column in asset.columns
        if column.get("name")
    ]
