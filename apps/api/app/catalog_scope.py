"""Which catalogued assets can actually be queried.

A file that is profiled but not staged is catalogued (schema ``file_profiles``)
so people can find it, but it has no physical table. Offering it to SQL
generation or grounding makes models write ``FROM file_profiles.<name>`` and
fail. Connector assets are queried on their own source and always count.
"""
from __future__ import annotations

import time

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from .database import engine
from .models import Connector, DataAsset

_TABLE_CACHE_SECONDS = 10.0
_tables: dict[str | None, tuple[float, set[str]]] = {}


def _physical_tables(schema: str | None) -> set[str]:
    cached = _tables.get(schema)
    now = time.monotonic()
    if cached and now - cached[0] < _TABLE_CACHE_SECONDS:
        return cached[1]
    try:
        inspector = inspect(engine)
        names = {name.lower() for name in inspector.get_table_names(schema=schema)} | {name.lower() for name in inspector.get_view_names(schema=schema)}
    except Exception:
        names = set()
    _tables[schema] = (now, names)
    return names


def local_table_exists(asset: DataAsset) -> bool:
    uses_schemas = engine.dialect.name == "postgresql"
    schema = None if not uses_schemas or asset.schema_name in {"", "main"} else asset.schema_name
    return asset.table_name.lower() in _physical_tables(schema)


def queryable_asset_ids(db: Session, project_id: str, assets: list[DataAsset] | None = None) -> set[str]:
    if assets is None:
        assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project_id)).all()
    local_connectors = set(
        db.scalars(select(Connector.id).where(Connector.project_id == project_id, Connector.connector_type == "local_files")).all()
    )
    return {
        asset.id
        for asset in assets
        if (asset.connector_id is not None and asset.connector_id not in local_connectors) or local_table_exists(asset)
    }


def reset_cache() -> None:
    _tables.clear()
