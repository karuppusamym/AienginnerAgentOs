from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .connector_runtime import discover_metadata
from .database import SessionLocal
from .governance import record_audit_event, record_governance_event
from .metadata_generation import is_unreviewed_description, suggest_dataset_metadata
from .models import AuditEvent, Connector, DataAsset, Job, SchemaDriftEvent, User
from .pii import annotate_columns
from .provider_selection import selected_model_provider
from .request_context import active_project_id
from .services.relationships import sync_view_lineage
from .vector_store import index_document

MAX_JOB_LOG_ENTRIES = 200


def append_job_log(job: Job, level: str, message: str) -> None:
    """Append a log entry, folding an identical consecutive entry into a repeat count and capping the log length."""
    now = datetime.now(timezone.utc).isoformat()
    logs = list(job.logs or [])
    last = logs[-1] if logs else None
    if last and last.get("level") == level and last.get("message") == message:
        logs[-1] = {**last, "repeat": int(last.get("repeat") or 1) + 1, "last_at": now}
    else:
        logs.append({"at": now, "level": level, "message": message})
    if len(logs) > MAX_JOB_LOG_ENTRIES:
        # Keep the first entry (when/how it was queued) and the most recent history.
        logs = [logs[0], {"at": now, "level": "warning", "message": f"{len(logs) - MAX_JOB_LOG_ENTRIES + 1} older log entries were dropped"}, *logs[-(MAX_JOB_LOG_ENTRIES - 2):]]
    job.logs = logs


def _connector_scan_jobs(db, connector: Connector, status: str, before: datetime) -> list[Job]:
    """Scan jobs of this connector in ``status`` created before ``before`` (older jobs name the connector only in their title)."""
    candidates = db.scalars(
        select(Job).where(Job.project_id == connector.project_id, Job.job_type == "metadata_scan", Job.status == status, Job.created_at < before)
    ).all()
    return [
        job for job in candidates
        if any(item.get("connector_id") == connector.id for item in job.evidence or [])
        or (not any(item.get("connector_id") for item in job.evidence or []) and job.title == f"Metadata scan: {connector.name}")
    ]


def supersede_failed_scans(db, connector: Connector, succeeded: Job) -> int:
    """A later successful scan resolves earlier failures of the same connector: mark them SUPERSEDED."""
    superseded = _connector_scan_jobs(db, connector, "FAILED", succeeded.created_at)
    for job in superseded:
        job.status = "SUPERSEDED"
        job.outputs = [*(job.outputs or []), {"type": "superseded", "title": "Superseded by a later successful scan", "summary": f"Scan job {succeeded.id} succeeded", "data": {"job_id": succeeded.id}, "at": datetime.now(timezone.utc).isoformat()}]
        append_job_log(job, "info", f"Superseded: a later scan of {connector.name} succeeded (job {succeeded.id[:8]})")
    return len(superseded)


def _keep_column_notes(previous: list[dict], current: list[dict]) -> list[dict]:
    """A rescan refreshes names and types but keeps business names and descriptions people (or the model) wrote."""
    notes = {str(column.get("name")): column for column in previous}
    merged = []
    for column in current:
        before = notes.get(str(column.get("name"))) or {}
        kept = {key: before[key] for key in ("business_name", "description") if before.get(key) and not str(before[key]).startswith("Input parameter (")}
        merged.append({**column, **kept})
    return merged


def _apply_ai_suggested_metadata(db, project_id: str, actor_id: str, asset: DataAsset, schema_name: str, table_name: str) -> None:
    """Fill in a description/column notes for a newly (re)discovered asset that nobody has reviewed yet.

    Best-effort only: any failure (no provider routed for this purpose, model
    error, malformed response) silently leaves the existing placeholder
    description in place. A scan must never fail because this enrichment did.
    """
    if not is_unreviewed_description(asset.description):
        return
    if any(column.get("business_name") for column in asset.columns):
        return
    actor = db.get(User, actor_id)
    if actor is None:
        return
    try:
        provider = selected_model_provider(db, actor, "metadata_generation")
    except Exception:
        provider = None
    if provider is None:
        return
    suggestion = suggest_dataset_metadata(
        provider, schema_name, table_name, asset.columns,
        governance_business_id=project_id, governance_user_id=actor.id,
    )
    if not suggestion:
        return
    asset.description = suggestion["description"]
    asset.metadata_status = "ai_suggested"
    asset.columns = [{**column, **suggestion["columns"].get(str(column.get("name", "")), {})} for column in asset.columns]


def _record_view_lineage(db, connector: Connector, view_items: list[tuple[DataAsset, str]]) -> None:
    """Base table -> view lineage from scanned view definitions. Best-effort:
    an unparseable definition must never fail the scan."""
    if not view_items:
        return
    connector_assets = db.scalars(select(DataAsset).where(DataAsset.project_id == connector.project_id, DataAsset.connector_id == connector.id)).all()
    for view, definition in view_items:
        try:
            sync_view_lineage(db, connector, view, definition, connector_assets)
        except Exception:
            continue


def execute_metadata_scan(connector_id: str, job_id: str, actor_id: str, attempt: int = 1, max_attempts: int = 1) -> dict:
    """Discover a connector's metadata. ``attempt``/``max_attempts`` come from the Temporal retry policy:
    a failed attempt that will be retried leaves the job RETRYING and only the last one marks it FAILED."""
    with SessionLocal() as db:
        connector = db.get(Connector, connector_id)
        job = db.get(Job, job_id)
        if connector is None or job is None:
            raise ValueError("Connector scan context no longer exists")
        if job.status in {"SUCCEEDED", "CANCELLED", "SUPERSEDED"}:
            return {"status": job.status, "summary": connector.metadata_summary or {}, "job_id": job.id, "assets_discovered": 0}
        job.status = "RUNNING"
        job.progress = 15
        append_job_log(job, "info", "Worker started metadata discovery" if attempt <= 1 else f"Retrying metadata discovery (attempt {attempt} of {max_attempts})")
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
                view_items: list[tuple[DataAsset, str]] = []
                # Pin the provider-selection context to the scanned connector's
                # project: this runs off the request thread (worker/threadpool),
                # so the ambient active_project_id contextvar is normally unset
                # and selected_model_provider() would otherwise fall back to the
                # actor's own "current project", which need not match the one
                # being scanned.
                context_token = active_project_id.set(connector.project_id)
                try:
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
                        asset.columns = _keep_column_notes(asset.columns or [], annotate_columns(item["columns"]))
                        asset.tags = item.get("tags", [])
                        asset.row_count = item.get("row_count")
                        if item.get("asset_type"):
                            asset.asset_type = item["asset_type"]
                        if is_unreviewed_description(asset.description) or (item.get("source_description") and asset.description == item["source_description"]):
                            asset.description = item.get("description_hint") or f"Discovered from {connector.name} in read-only mode."
                        _apply_ai_suggested_metadata(db, connector.project_id, actor_id, asset, item["schema_name"], item["table_name"])
                        discovered_assets.append(asset)
                        if item.get("view_definition"):
                            view_items.append((asset, item["view_definition"]))
                    _record_view_lineage(db, connector, view_items)
                finally:
                    active_project_id.reset(context_token)
            connector.status = "healthy"
            connector.last_scanned_at = datetime.now(timezone.utc)
            connector.metadata_summary = summary
            job.status = "SUCCEEDED"
            job.progress = 100
            job.plan = [{**step, "status": "complete"} for step in job.plan]
            append_job_log(job, "info", f"Discovered {summary['tables']} tables and {summary['columns']} columns")
            superseded = supersede_failed_scans(db, connector, job)
            if superseded:
                append_job_log(job, "info", f"Marked {superseded} earlier failed scan{'s' if superseded != 1 else ''} of this connector as superseded")
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
                        db=db,
                    )
                except Exception:
                    pass
            return {"status": "SUCCEEDED", "summary": summary, "job_id": job.id, "assets_discovered": len(discovered_assets)}
        except Exception as exc:
            db.rollback()
            job = db.get(Job, job_id)
            connector = db.get(Connector, connector_id)
            if attempt < max_attempts and not isinstance(exc, ValueError):
                job.status = "RETRYING"
                append_job_log(job, "warning", f"Attempt {attempt} of {max_attempts} failed: {exc}")
                db.commit()
                raise
            connector.status = "error"
            job.status = "FAILED"
            job.progress = 100
            append_job_log(job, "error", f"{exc}" if max_attempts <= 1 else f"Failed after {attempt} attempt{'s' if attempt != 1 else ''}: {exc}")
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
