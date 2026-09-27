"""Superset embedding: pick the project dataset and persist provisioned dashboard state."""
from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from ..database import engine
from ..models import (
    Artifact,
    DataAsset,
    IngestionMapping,
    Project,
    SupersetProjectDashboard,
    SupersetQueryDashboard,
)


def _superset_dataset(asset: DataAsset, project: Project) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "project_slug": project.slug,
        "schema_name": asset.schema_name,
        "table_name": asset.table_name,
        "columns": list(asset.columns or []),
        "source_name": asset.source_name,
        "asset_type": asset.asset_type,
        "row_count": asset.row_count,
    }


def resolve_superset_dataset(db: Session, project: Project) -> dict[str, Any]:
    inspector = inspect(engine)
    known_tables: dict[str | None, set[str]] = {}
    uses_schemas = engine.dialect.name == "postgresql"

    def table_exists(asset: DataAsset) -> bool:
        schema = None if not uses_schemas or asset.schema_name in {"", "main"} else asset.schema_name
        if schema not in known_tables:
            known_tables[schema] = set(inspector.get_table_names(schema=schema))
        return asset.table_name in known_tables[schema]

    latest_mapping = db.scalar(
        select(IngestionMapping)
        .where(
            IngestionMapping.project_id == project.id,
            IngestionMapping.latest_relation.is_not(None),
        )
        .order_by(IngestionMapping.updated_at.desc())
    )
    if latest_mapping and latest_mapping.latest_relation:
        relation = latest_mapping.latest_relation
        if "." in relation:
            schema_name, table_name = relation.split(".", 1)
        else:
            schema_name, table_name = "main", relation
        asset = db.scalar(
            select(DataAsset).where(
                DataAsset.project_id == project.id,
                DataAsset.schema_name == schema_name,
                DataAsset.table_name == table_name,
            )
        )
        if asset is not None and table_exists(asset):
            return _superset_dataset(asset, project)

    assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project.id)).all()
    candidates = [asset for asset in assets if table_exists(asset)]
    if not candidates:
        raise ValueError(
            "Load, schedule, or publish a local project dataset before opening Superset"
        )

    def asset_priority(asset: DataAsset) -> tuple[int, int, int, int, str]:
        source_rank = 0 if asset.source_name == "Local files" else 1 if asset.source_name == "DataPilot pipelines" else 2
        type_rank = 0 if asset.asset_type in {"staged_file", "view"} else 1
        schema_rank = 0 if asset.schema_name == "staging" else 1
        row_rank = -(asset.row_count or 0)
        return (
            source_rank,
            type_rank,
            schema_rank,
            row_rank,
            f"{asset.schema_name}.{asset.table_name}",
        )

    return _superset_dataset(sorted(candidates, key=asset_priority)[0], project)


def save_superset_dashboard_state(
    db: Session,
    project: Project,
    dataset: dict[str, Any],
    config: dict[str, Any],
) -> SupersetProjectDashboard:
    state = db.scalar(
        select(SupersetProjectDashboard).where(SupersetProjectDashboard.project_id == project.id)
    )
    if state is None:
        state = SupersetProjectDashboard(project_id=project.id)
        db.add(state)
    state.dashboard_id = int(config["dashboard_id"]) if config.get("dashboard_id") is not None else None
    state.dashboard_slug = str(config.get("dashboard_slug", ""))[:160]
    state.embedded_id = str(config["embedded_id"]) if config.get("embedded_id") else None
    state.dashboard_title = str(config.get("dashboard_title", ""))[:240]
    state.superset_dataset_id = (
        int(config["superset_dataset_id"]) if config.get("superset_dataset_id") is not None else None
    )
    state.dataset_schema_name = str(dataset.get("schema_name", ""))[:120]
    state.dataset_table_name = str(dataset.get("table_name", ""))[:160]
    state.dataset_column_count = len(list(dataset.get("columns") or []))
    chart_ids = config.get("chart_ids") or []
    state.chart_ids = [int(chart_id) for chart_id in chart_ids if isinstance(chart_id, int) or str(chart_id).isdigit()]
    state.access_mode = str(config.get("access_mode", "dashboard_scope"))[:64]
    state.rls_column = str(config["rls_column"])[:160] if config.get("rls_column") else None
    db.flush()
    return state


def save_superset_query_dashboard_state(
    db: Session,
    project: Project,
    artifact: Artifact,
    artifact_version: int,
    sql: str,
    columns: list[dict[str, Any]],
    config: dict[str, Any],
    published_by: str,
) -> SupersetQueryDashboard:
    """Persist the dedicated dashboard provisioned for one published SQL/notebook query.

    Keyed by (project_id, artifact_id) so re-publishing a later version of the
    same saved artifact updates its existing dedicated dashboard instead of
    creating a duplicate — mirroring how save_superset_dashboard_state treats
    the project's primary dashboard as a stable, upsertable identity.
    """
    state = db.scalar(
        select(SupersetQueryDashboard).where(
            SupersetQueryDashboard.project_id == project.id,
            SupersetQueryDashboard.artifact_id == artifact.id,
        )
    )
    if state is None:
        state = SupersetQueryDashboard(project_id=project.id, artifact_id=artifact.id, published_by=published_by)
        db.add(state)
    state.artifact_version = artifact_version
    state.query_name = str(config.get("dataset_relation", "")).split(".")[-1][:160]
    state.sql = sql[:20000]
    state.columns = columns
    state.dashboard_id = int(config["dashboard_id"]) if config.get("dashboard_id") is not None else None
    state.dashboard_slug = str(config.get("dashboard_slug", ""))[:160]
    state.embedded_id = str(config["embedded_id"]) if config.get("embedded_id") else None
    state.dashboard_title = str(config.get("dashboard_title", ""))[:240]
    state.superset_dataset_id = (
        int(config["superset_dataset_id"]) if config.get("superset_dataset_id") is not None else None
    )
    chart_ids = config.get("chart_ids") or []
    state.chart_ids = [int(chart_id) for chart_id in chart_ids if isinstance(chart_id, int) or str(chart_id).isdigit()]
    state.access_mode = str(config.get("access_mode", "dashboard_scope"))[:64]
    state.rls_column = str(config["rls_column"])[:160] if config.get("rls_column") else None
    state.published_by = published_by
    db.flush()
    return state


def _table_exists_check():
    inspector = inspect(engine)
    known_tables: dict[str | None, set[str]] = {}
    uses_schemas = engine.dialect.name == "postgresql"

    def table_exists(asset: DataAsset) -> bool:
        schema = None if not uses_schemas or asset.schema_name in {"", "main"} else asset.schema_name
        if schema not in known_tables:
            try:
                known_tables[schema] = set(inspector.get_table_names(schema=schema)) | set(inspector.get_view_names(schema=schema))
            except Exception:
                known_tables[schema] = set()
        return asset.table_name in known_tables[schema]

    return table_exists


def local_analytics_datasets(db: Session, project: Project) -> list[DataAsset]:
    """Catalogued datasets Superset can chart: local to the analytics database and physically present.

    Connector sources (SQL Server, Oracle, ...) are not registered in Superset,
    and DataPilot's own metadata tables are never offered.
    """
    from ..models import Connector
    from ..staging import application_relations

    local_connectors = {
        connector.id
        for connector in db.scalars(select(Connector).where(Connector.project_id == project.id, Connector.connector_type == "local_files")).all()
    }
    app_tables = application_relations()
    table_exists = _table_exists_check()
    assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project.id)).all()
    return [
        asset
        for asset in assets
        if (asset.connector_id is None or asset.connector_id in local_connectors)
        and asset.table_name.lower() not in app_tables
        and table_exists(asset)
    ]


def dataset_dashboard_payload(asset: DataAsset, project: Project) -> dict[str, Any]:
    """A dataset dict for a per-dataset dashboard; PII-named columns are left out of the charts."""
    from ..pii import pii_category

    dataset = _superset_dataset(asset, project)
    dataset["columns"] = [column for column in dataset["columns"] if not pii_category(str(column.get("name") or ""))]
    return dataset
