"""Frictionless Data Package (Open Knowledge Foundation) export and metadata import."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import engine, get_db
from ..frictionless import asset_resource, data_package, metadata_changes, resource_name, validate_descriptor
from ..core import DataAssetUpdate, audit, require_current_project, require_project_resource
from ..models import DataAsset, User
from ..staging import execute_read_only
from .workspace import update_dataset_metadata

router = APIRouter()

INLINE_ROW_LIMIT = 1_000


@router.get("/datapackage")
def export_project_datapackage(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Whole-project catalog as a schema-only Data Package."""
    project = require_current_project(db, user)
    assets = db.scalars(
        select(DataAsset).where(DataAsset.project_id == project.id).order_by(DataAsset.schema_name, DataAsset.table_name)
    ).all()
    audit(db, user, "datapackage.exported", "project", project.id, {"resources": len(assets), "inline_data": False})
    db.commit()
    return data_package(project.name, f"{project.name} catalog", [asset_resource(asset) for asset in assets], project.description or None)


@router.get("/datasets/{asset_id}/datapackage")
def export_dataset_datapackage(
    asset_id: str,
    include_data: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=INLINE_ROW_LIMIT),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    asset = require_project_resource(db.get(DataAsset, asset_id), project, "Dataset")
    rows = None
    if include_data:
        if asset.connector_id is not None:
            raise HTTPException(status_code=409, detail="Inline data is available only for locally staged datasets; external sources stay behind their governed query tools")
        relation = f"{asset.schema_name}.{asset.table_name}" if asset.schema_name not in {"", "main"} else asset.table_name
        try:
            # Through the governed read-only path, so PII masking applies to exported rows too.
            rows = execute_read_only(engine, f"SELECT * FROM {relation}", limit)["rows"]
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"Could not read {relation}: {str(exc)[:300]}") from exc
    audit(db, user, "datapackage.exported", "data_asset", asset.id, {"inline_data": include_data, "rows": len(rows or [])})
    db.commit()
    return data_package(resource_name(asset), asset.table_name, [asset_resource(asset, rows)], asset.description)


@router.post("/datapackage/validate")
def validate_datapackage(descriptor: dict[str, Any] = Body(...), _: User = Depends(get_current_user)) -> dict[str, Any]:
    errors = validate_descriptor(descriptor)
    return {"valid": not errors, "errors": errors}


@router.post("/datasets/{asset_id}/datapackage")
def apply_datapackage_metadata(
    asset_id: str,
    descriptor: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Apply curated titles/descriptions/tags from a Data Package back onto a catalog asset."""
    project = require_current_project(db, user)
    asset = require_project_resource(db.get(DataAsset, asset_id), project, "Dataset")
    errors = validate_descriptor(descriptor)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Invalid Data Package descriptor", "errors": errors})
    resources = descriptor["resources"]
    resource = next(
        (item for item in resources if item.get("datapilot:assetId") == asset.id or item.get("name") == resource_name(asset)),
        resources[0] if len(resources) == 1 else None,
    )
    if resource is None:
        raise HTTPException(status_code=422, detail=f"No resource named {resource_name(asset)} in the descriptor")
    patch = metadata_changes(asset, resource)
    # Reuses the dataset editor path so role checks and audit stay in one place.
    updated = update_dataset_metadata(asset.id, DataAssetUpdate(**patch), user, db)
    return {"applied": sorted(patch), "columns_updated": sorted((patch.get("column_notes") or {}).keys()), "dataset": updated}
