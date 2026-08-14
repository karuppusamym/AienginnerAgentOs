from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from croniter import croniter
from sqlalchemy import select

from .database import SessionLocal, engine
from .file_profiles import read_structured_rows
from .governance import record_governance_event
from .models import DataAsset, IngestedFile, IngestionMapping, IngestionSchedule, Job
from .staging import stage_rows
from .vector_store import index_document


def next_run_at(expression: str, base: datetime | None = None) -> datetime:
    if not croniter.is_valid(expression):
        raise ValueError("The cron expression is invalid")
    anchor = base or datetime.now(timezone.utc)
    value = croniter(expression, anchor).get_next(datetime)
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def _watermark_value(value: Any) -> tuple[int, Any]:
    if value is None or value == "":
        return (0, "")
    text = str(value)
    try:
        return (2, Decimal(text))
    except InvalidOperation:
        pass
    try:
        return (3, datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return (1, text)


def run_ingestion_schedule(schedule_id: str, actor_id: str | None = None) -> dict[str, Any]:
    with SessionLocal() as db:
        schedule = db.get(IngestionSchedule, schedule_id)
        if schedule is None:
            raise ValueError("Ingestion schedule not found")
        mapping = db.get(IngestionMapping, schedule.mapping_id)
        item = db.get(IngestedFile, mapping.file_id) if mapping else None
        if mapping is None or item is None:
            raise ValueError("The scheduled mapping or source file no longer exists")

        user_id = actor_id or schedule.created_by
        job = Job(
            project_id=schedule.project_id,
            title=f"Scheduled ingestion: {schedule.name}",
            job_type="scheduled_ingestion",
            status="RUNNING",
            progress=15,
            created_by=user_id,
            plan=[
                {"agent": "Scheduler", "action": "Resolve due schedule", "status": "complete"},
                {"agent": "Watermark", "action": "Select incremental source rows", "status": "running"},
                {"agent": "Runner", "action": "Apply governed load mode", "status": "pending"},
                {"agent": "Metadata", "action": "Publish run evidence", "status": "pending"},
            ],
            evidence=[{"type": "schedule", "label": schedule.name}],
            logs=[{"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Scheduled run started"}],
        )
        db.add(job)
        db.flush()
        record_governance_event(
            "worker_job",
            "scheduled_ingestion",
            "started",
            project_id=schedule.project_id,
            user_id=user_id,
            session_id=job.id,
            schedule_id=schedule.id,
            load_mode=schedule.load_mode,
        )
        try:
            rows = read_structured_rows(Path(item.storage_path), Path(item.filename).suffix.lower())
            if rows is None:
                raise ValueError("The scheduled source is not structured data")

            watermark_source = None
            if schedule.watermark_column:
                watermark_source = next(
                    (
                        column["source_name"]
                        for column in mapping.columns
                        if column["target_name"] == schedule.watermark_column
                    ),
                    None,
                )
                if watermark_source is None:
                    raise ValueError("The watermark column is not present in the mapping")
                if schedule.last_watermark is not None:
                    previous = _watermark_value(schedule.last_watermark)
                    rows = [row for row in rows if _watermark_value(row.get(watermark_source)) > previous]

            if not rows:
                job.status = "SUCCEEDED"
                job.progress = 100
                job.plan = [{**step, "status": "complete"} for step in job.plan]
                job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "No rows were newer than the stored watermark"}]
                schedule.last_run_at = datetime.now(timezone.utc)
                schedule.next_run_at = next_run_at(schedule.cron, schedule.last_run_at)
                db.commit()
                record_governance_event(
                    "scheduled_ingestion",
                    schedule.load_mode,
                    "succeeded",
                    project_id=schedule.project_id,
                    user_id=user_id,
                    session_id=job.id,
                    schedule_id=schedule.id,
                    loaded_rows=0,
                    no_new_rows=True,
                )
                return {"job_id": job.id, "status": job.status, "loaded_rows": 0, "relation": mapping.latest_relation}

            target_table = mapping.target_table
            source_file_id = item.id
            mapped_columns = list(mapping.columns)
            load_mode = schedule.load_mode
            key_columns = list(schedule.key_columns)
            db.commit()
            staged = stage_rows(
                engine,
                target_table,
                source_file_id,
                mapped_columns,
                rows,
                load_mode=load_mode,
                key_columns=key_columns,
            )
            if watermark_source:
                latest = max(rows, key=lambda row: _watermark_value(row.get(watermark_source)))
                schedule.last_watermark = str(latest.get(watermark_source))
            schedule.last_run_at = datetime.now(timezone.utc)
            schedule.next_run_at = next_run_at(schedule.cron, schedule.last_run_at)
            mapping.latest_relation = staged["relation"]
            mapping.run_count += 1
            item.status = "staged"
            item.profile = {
                **item.profile,
                "staged_table": staged,
                "confirmed_mapping": {
                    "id": mapping.id,
                    "name": mapping.name,
                    "target_table": mapping.target_table,
                    "columns": mapping.columns,
                    "load_mode": schedule.load_mode,
                    "key_columns": schedule.key_columns,
                },
            }
            asset = db.scalar(
                select(DataAsset).where(
                    DataAsset.project_id == schedule.project_id,
                    DataAsset.source_name == "Local files",
                    DataAsset.schema_name == staged["schema_name"],
                    DataAsset.table_name == staged["table_name"],
                )
            )
            if asset is None:
                asset = DataAsset(
                    project_id=schedule.project_id,
                    source_name="Local files",
                    schema_name=staged["schema_name"],
                    table_name=staged["table_name"],
                    asset_type="staged_file",
                )
                db.add(asset)
            asset.row_count = staged["row_count"]
            asset.columns = [
                {"name": column["name"], "type": column["type"], "nullable": True}
                for column in staged["columns"]
            ]
            asset.tags = ["local-file", "scheduled", schedule.load_mode]
            asset.description = f"Scheduled ingestion from {item.filename}"
            job.status = "SUCCEEDED"
            job.progress = 100
            job.plan = [{**step, "status": "complete"} for step in job.plan]
            job.evidence = [
                *job.evidence,
                {"type": "dataset", "label": staged["relation"]},
                {"type": "rows", "label": f"{staged['loaded_rows']} rows loaded"},
            ]
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Loaded {staged['loaded_rows']} rows to {staged['relation']}"}]
            db.commit()
            record_governance_event(
                "scheduled_ingestion",
                schedule.load_mode,
                "succeeded",
                project_id=schedule.project_id,
                user_id=user_id,
                session_id=job.id,
                schedule_id=schedule.id,
                loaded_rows=staged["loaded_rows"],
                row_count=staged["row_count"],
            )
            try:
                index_document(
                    asset.id,
                    staged["relation"],
                    f"Scheduled local dataset with {staged['row_count']} rows",
                    {"source_type": "dataset", "schema_name": staged["schema_name"], "table_name": staged["table_name"], "tags": asset.tags},
                    db=db,
                )
            except Exception:
                pass
            return {"job_id": job.id, "status": job.status, "loaded_rows": staged["loaded_rows"], "relation": staged["relation"], "last_watermark": schedule.last_watermark}
        except Exception as exc:
            job.status = "FAILED"
            job.progress = 100
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "error", "message": str(exc)[:2000]}]
            schedule.last_run_at = datetime.now(timezone.utc)
            schedule.next_run_at = next_run_at(schedule.cron, schedule.last_run_at)
            db.commit()
            record_governance_event(
                "scheduled_ingestion",
                schedule.load_mode,
                "failed",
                project_id=schedule.project_id,
                user_id=user_id,
                session_id=job.id,
                schedule_id=schedule.id,
                error_type=type(exc).__name__,
            )
            raise


def due_schedule_ids(now: datetime | None = None) -> list[str]:
    current = now or datetime.now(timezone.utc)
    with SessionLocal() as db:
        schedules = db.scalars(
            select(IngestionSchedule).where(
                IngestionSchedule.enabled.is_(True),
                IngestionSchedule.next_run_at <= current,
            )
        ).all()
        return [schedule.id for schedule in schedules]
