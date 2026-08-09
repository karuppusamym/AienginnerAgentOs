from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .connector_runtime import discover_metadata
from .database import SessionLocal
from .governance import record_audit_event, record_governance_event
from .models import AuditEvent, Connector, DataAsset, Job, SchemaDriftEvent
from .pii import annotate_columns
from .vector_store import index_document


def execute_metadata_scan(connector_id: str, job_id: str, actor_id: str) -> dict:
    with SessionLocal() as db:
        connector = db.get(Connector, connector_id)
        job = db.get(Job, job_id)
        if connector is None or job is None:
            raise ValueError("Connector scan context no longer exists")
        job.status = "RUNNING"
        job.progress = 15
        job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Worker started metadata discovery"}]
        db.commit()
        record_governance_event(
            "worker_job",
            "metadata_scan",
            "started",
            project_id=connector.project_id,
            user_id=actor_id,
            session_id=job.id,
            connector_id=connector.id,
        )
        try:
            if connector.host == "mock-sqlserver":
                discovered_assets = db.scalars(select(DataAsset).where(DataAsset.project_id == connector.project_id, DataAsset.connector_id == connector.id)).all()
                summary = {
                    "schemas": len({asset.schema_name for asset in discovered_assets}),
                    "tables": len(discovered_assets),
                    "columns": sum(len(asset.columns) for asset in discovered_assets),
                }
            elif connector.connector_type == "local_files":
                discovered_assets = db.scalars(select(DataAsset).where(DataAsset.project_id == connector.project_id, DataAsset.source_name == "Local files")).all()
                summary = {
                    "schemas": len({asset.schema_name for asset in discovered_assets}),
                    "tables": len(discovered_assets),
                    "columns": sum(len(asset.columns) for asset in discovered_assets),
                }
            else:
                discovery = discover_metadata(connector)
                summary = discovery.summary
                discovered_assets = []
                for item in discovery.assets:
                    asset = db.scalar(
                        select(DataAsset).where(
                            DataAsset.project_id == connector.project_id,
                            DataAsset.connector_id == connector.id,
                            DataAsset.schema_name == item["schema_name"],
                            DataAsset.table_name == item["table_name"],
                        )
                    )
                    if asset is None:
                        asset = DataAsset(
                            project_id=connector.project_id,
                            connector_id=connector.id,
                            source_name=connector.name,
                            schema_name=item["schema_name"],
                            table_name=item["table_name"],
                        )
                        db.add(asset)
                        db.flush()
                    else:
                        previous = {str(column.get("name")): str(column.get("type")) for column in asset.columns}
                        current = {str(column.get("name")): str(column.get("type")) for column in item["columns"]}
                        changes = [
                            *[{"kind": "column_added", "column": name, "type": current[name]} for name in sorted(current.keys() - previous.keys())],
                            *[{"kind": "column_removed", "column": name, "type": previous[name]} for name in sorted(previous.keys() - current.keys())],
                            *[{"kind": "type_changed", "column": name, "from": previous[name], "to": current[name]} for name in sorted(previous.keys() & current.keys()) if previous[name].lower() != current[name].lower()],
                        ]
                        if changes:
                            db.add(SchemaDriftEvent(project_id=connector.project_id, connector_id=connector.id, asset_id=asset.id, relation=f"{item['schema_name']}.{item['table_name']}", changes=changes))
                    asset.columns = annotate_columns(item["columns"])
                    asset.tags = item.get("tags", [])
                    asset.row_count = item.get("row_count")
                    asset.description = item.get("description_hint") or f"Discovered from {connector.name} in read-only mode."
                    discovered_assets.append(asset)
            connector.status = "healthy"
            connector.last_scanned_at = datetime.now(timezone.utc)
            connector.metadata_summary = summary
            job.status = "SUCCEEDED"
            job.progress = 100
            job.plan = [{**step, "status": "complete"} for step in job.plan]
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Discovered {summary['tables']} tables and {summary['columns']} columns"}]
            db.add(AuditEvent(project_id=connector.project_id, actor_id=actor_id, event_type="connector.scanned", entity_type="connector", entity_id=connector.id, details=summary))
            db.commit()
            record_audit_event(
                "connector.scanned",
                "connector",
                connector.id,
                project_id=connector.project_id,
                user_id=actor_id,
                details=summary,
            )
            record_governance_event(
                "connector_scan",
                connector.connector_type,
                "succeeded",
                project_id=connector.project_id,
                user_id=actor_id,
                session_id=job.id,
                connector_id=connector.id,
                **summary,
            )
            for asset in discovered_assets:
                try:
                    index_document(
                        asset.id,
                        f"{asset.schema_name}.{asset.table_name}",
                        f"{asset.description or ''} Columns: " + ", ".join(column.get("name", "") for column in asset.columns),
                        {"source_type": "dataset", "schema_name": asset.schema_name, "table_name": asset.table_name, "tags": asset.tags},
                    )
                except Exception:
                    pass
            return {"status": "SUCCEEDED", "summary": summary, "job_id": job.id, "assets_discovered": len(discovered_assets)}
        except Exception as exc:
            connector.status = "error"
            job.status = "FAILED"
            job.progress = 100
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "error", "message": str(exc)}]
            db.add(AuditEvent(project_id=connector.project_id, actor_id=actor_id, event_type="connector.scan_failed", entity_type="connector", entity_id=connector.id, details={"error": str(exc)}))
            db.commit()
            record_audit_event(
                "connector.scan_failed",
                "connector",
                connector.id,
                project_id=connector.project_id,
                user_id=actor_id,
                details={"error": str(exc)},
            )
            record_governance_event(
                "connector_scan",
                connector.connector_type,
                "failed",
                project_id=connector.project_id,
                user_id=actor_id,
                session_id=job.id,
                connector_id=connector.id,
                error_type=type(exc).__name__,
            )
            raise
