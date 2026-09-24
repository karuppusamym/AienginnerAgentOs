"""Runs one bounded external-DB-to-staging extraction batch.

Extracted from the former inline body of the
`POST /external-extractions/{id}/run` route handler so the same logic can
run two ways: synchronously (direct HTTP call, the original and still-default
behavior) or as a Temporal activity (durable, retryable, off the API request
thread -- see `start_external_extraction_workflow()` in `temporal_runtime.py`
and `ExternalExtractionWorkflow` in `temporal_workflows.py`).

This closes a real inconsistency: metadata scans and scheduled file
ingestion both already had a Temporal-backed async path with a synchronous
fallback; external extractions were the one ingestion path that only ever
ran synchronously inside the HTTP request, blocking a request-handling
thread for the query duration with no durability, retry, or cancellation --
see `IMPLEMENTATION_STATUS_MATRIX.md` for the full write-up. Mirrors the
same dual-path pattern already used by `run_ingestion_schedule()` in
`schedule_runtime.py`.

Imports from `main` are deferred to call time (inside the function body),
not module load time, to avoid a circular import: this module is reachable
from `temporal_activities.py`, which `routers/sql.py` imports while
`main.py` is still defining itself -- the same reason `schedule_runtime.py`
never imports from `main` at module scope either.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .database import SessionLocal
from .governance import record_governance_event
from .models import Connector, DataAsset, ExternalExtraction, Job, LineageEdge
from .staging import stage_rows


def run_external_extraction_now(extraction_id: str, actor_id: str | None = None) -> dict[str, Any]:
    from . import core as main  # deferred: see module docstring (shared services live in core)

    with SessionLocal() as db:
        extraction = db.get(ExternalExtraction, extraction_id)
        if extraction is None:
            raise ValueError("External extraction not found")
        connector = db.get(Connector, extraction.connector_id)
        if connector is None or connector.project_id != extraction.project_id:
            raise ValueError("Connector not found")
        asset = db.get(DataAsset, extraction.source_asset_id)
        if asset is None or asset.project_id != extraction.project_id:
            raise ValueError("Source data asset not found")
        if connector.connection_mode != "direct" or not connector.read_only:
            raise ValueError("The extraction source must remain a read-only direct connector")

        user_id = actor_id or extraction.created_by
        relation, relation_sql = main._asset_relation_sql(asset, connector)
        query_parameters: dict[str, Any] = {}
        source_sql = f"SELECT * FROM {relation_sql}"
        if extraction.watermark_column:
            watermark_column = main._identifier_quote(extraction.watermark_column, main.connector_dialect(connector, "postgres"))
            if extraction.last_watermark is not None:
                source_sql += f" WHERE {watermark_column} > :watermark"
                query_parameters["watermark"] = extraction.last_watermark
            source_sql += f" ORDER BY {watermark_column} ASC"

        job = Job(
            project_id=extraction.project_id,
            title=f"External extraction: {extraction.name}",
            job_type="external_extraction",
            status="RUNNING",
            progress=20,
            plan=[
                {"agent": "Connector", "action": "Run bounded read-only source query", "status": "running"},
                {"agent": "Staging", "action": "Load normalized rows into local staging", "status": "pending"},
                {"agent": "Metadata", "action": "Update catalog and lineage evidence", "status": "pending"},
            ],
            evidence=[
                {"type": "source", "label": relation},
                {"type": "target", "label": f"staging.{extraction.target_table}"},
                {"type": "load_mode", "label": extraction.load_mode},
            ],
            created_by=user_id,
        )
        db.add(job)
        db.flush()
        # stage_rows uses an independent engine transaction, so release the job insert first.
        db.commit()
        record_governance_event(
            "external_extraction", connector.connector_type, "started",
            project_id=extraction.project_id, user_id=user_id, session_id=job.id,
            extraction_id=extraction.id, connector_id=connector.id, batch_limit=extraction.batch_limit,
        )
        try:
            source_result = main.execute_connector_query(
                connector, source_sql, query_parameters, extraction.batch_limit, 60,
                user_id=user_id, session_id=job.id, feature="external_extraction",
            )
            source_rows = source_result["rows"]
            expected_source_columns = {
                str(column["source_name"]) for column in main.external_extraction_columns(asset)
            }
            returned_columns = {str(column) for column in source_result["columns"]}
            missing_source_columns = sorted(expected_source_columns - returned_columns)
            if missing_source_columns:
                raise ValueError(
                    "Source schema no longer matches the scanned asset; rescan before extraction. "
                    f"Missing columns: {', '.join(missing_source_columns)}"
                )
            if source_result["truncated"] and not extraction.watermark_column:
                raise ValueError("A truncated external extract requires a watermark column before it can be staged")
            staged = stage_rows(
                main.engine, extraction.target_table, extraction.id,
                main.external_extraction_columns(asset), source_rows,
                load_mode=extraction.load_mode, key_columns=extraction.key_columns,
            )
            if extraction.watermark_column and source_rows:
                extraction.last_watermark = str(source_rows[-1].get(extraction.watermark_column))
            extraction.latest_relation = staged["relation"]
            extraction.run_count += 1
            extraction.status = "active"
            target_asset = db.scalar(
                select(DataAsset).where(
                    DataAsset.project_id == extraction.project_id,
                    DataAsset.source_name == f"External extraction: {connector.name}",
                    DataAsset.schema_name == staged["schema_name"],
                    DataAsset.table_name == staged["table_name"],
                )
            )
            if target_asset is None:
                target_asset = DataAsset(
                    project_id=extraction.project_id,
                    source_name=f"External extraction: {connector.name}",
                    schema_name=staged["schema_name"],
                    table_name=staged["table_name"],
                    asset_type="staged_extract",
                )
                db.add(target_asset)
                db.flush()
            target_asset.row_count = staged["row_count"]
            target_asset.columns = [
                {"name": column["name"], "type": column["type"], "nullable": True}
                for column in staged["columns"]
            ]
            target_asset.tags = ["external-extract", connector.connector_type, extraction.load_mode]
            target_asset.description = f"Read-only extraction from {connector.name} {relation}"
            edge = db.scalar(
                select(LineageEdge).where(
                    LineageEdge.project_id == extraction.project_id,
                    LineageEdge.source_asset_id == asset.id,
                    LineageEdge.target_asset_id == target_asset.id,
                    LineageEdge.pipeline_id.is_(None),
                )
            )
            if edge is None:
                edge = LineageEdge(
                    project_id=extraction.project_id,
                    source_asset_id=asset.id,
                    target_asset_id=target_asset.id,
                    source_relation=relation,
                    target_relation=staged["relation"],
                    transformation=f"Read-only external extraction via {connector.name}",
                    column_mapping=[{"source": column["source_name"], "target": column["name"]} for column in staged["columns"]],
                )
                db.add(edge)
            else:
                edge.target_relation = staged["relation"]
                edge.column_mapping = [{"source": column["source_name"], "target": column["name"]} for column in staged["columns"]]
            job.status = "SUCCEEDED"
            job.progress = 100
            job.plan = [{**step, "status": "complete"} for step in job.plan]
            job.evidence = [*job.evidence, {"type": "rows", "label": f"{staged['loaded_rows']} rows loaded"}, {"type": "lineage", "label": f"{relation} -> {staged['relation']}"}]
            job.outputs = [{"type": "extraction", "title": "Staged external data", "summary": f"Loaded {staged['loaded_rows']} rows", "data": {"source": relation, "target": staged["relation"], "truncated": source_result["truncated"]}, "at": datetime.now(timezone.utc).isoformat()}]
            record_governance_event(
                "external_extraction", connector.connector_type, "succeeded",
                project_id=extraction.project_id, user_id=user_id, session_id=job.id,
                extraction_id=extraction.id, connector_id=connector.id,
                loaded_rows=staged["loaded_rows"], row_count=staged["row_count"], truncated=source_result["truncated"],
            )
            db.commit()
            return {**main.external_extraction_output(extraction, db), "job_id": job.id, "loaded_rows": staged["loaded_rows"], "row_count": staged["row_count"]}
        except Exception as exc:
            extraction.status = "failed"
            job.status = "FAILED"
            job.progress = 100
            job.logs = [{"at": datetime.now(timezone.utc).isoformat(), "level": "error", "message": str(exc)[:2_000]}]
            record_governance_event(
                "external_extraction", connector.connector_type, "failed",
                project_id=extraction.project_id, user_id=user_id, session_id=job.id,
                extraction_id=extraction.id, connector_id=connector.id, error_type=type(exc).__name__,
            )
            db.commit()
            raise
