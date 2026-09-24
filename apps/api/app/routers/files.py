"""Auto-extracted files routes from the former monolithic main.py.

Generated as part of the DataPilot backend restructuring effort
(docs/IMPLEMENTATION_STATUS_MATRIX.md, section 3). Behavior is unchanged;
route handlers were relocated verbatim from apps/api/app/main.py and now
live on a domain-scoped APIRouter instead of the global FastAPI app.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from difflib import unified_diff
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.orm import Session
from ..auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from ..governance import initialize_governance, record_audit_event
from ..connector_runtime import ConnectorRuntimeError, test_connection
from ..database import Base, SessionLocal, engine, get_db
from ..demo_data import ensure_demo_tables
from ..file_profiles import profile_file, read_structured_rows
from ..grounding import context_signature, grounding_context, grounding_prompt_text, normalize_query, project_grounding_signature
from ..model_runtime import generate_text, test_provider as invoke_provider_test
from ..metadata_scan_runtime import execute_metadata_scan
from ..models import (
    AgentDefinition,
    AgentVersion,
    Approval,
    Artifact,
    ArtifactComment,
    ArtifactVersion,
    AuditEvent,
    AuthProvider,
    Connector,
    Conversation,
    ConversationMessage,
    DataAsset,
    ExternalExtraction,
    IngestedFile,
    IngestionMapping,
    IngestionSchedule,
    Incident,
    Job,
    LearningSuggestion,
    LineageEdge,
    EvaluationRun,
    EvaluationSet,
    ExternalClient,
    ExternalInvocation,
    ModelCallLog,
    ModelProvider,
    Project,
    ProjectMembership,
    PipelineDefinition,
    PipelineVersion,
    QualityRule,
    QualityRun,
    QueryTool,
    QueryToolGrant,
    RetentionPolicy,
    SchemaDriftEvent,
    SQLQueryCache,
    SemanticJoinPolicy,
    SemanticMetric,
    SupersetProjectDashboard,
    ToolDefinition,
    ToolExecution,
    ToolVersion,
    User,
    UserFeedback,
)
from ..provider_selection import selected_model_provider
from ..quality import execute_quality_rule
from ..notebook_runtime import execute_notebook
from ..observability import elapsed_ms, emit, initialize_observability, request_id, span, status as observability_status
from ..pipeline_codegen import (
    DEFAULT_ARTIFACT_TARGETS,
    PipelineGenerationError,
    build_exported_package,
    create_package_archive,
    emit_pipeline_artifacts,
    plan_pipeline,
    validate_exported_package,
    validate_pipeline_artifacts,
    validate_pipeline_spec,
)
from ..schedule_runtime import next_run_at, run_ingestion_schedule
from ..schema_migrations import backfill_project_columns, ensure_project_columns
from ..seed import seed_database
from ..staging import execute_parameterized_read_only, execute_read_only, safe_identifier, stage_rows
from ..pii import annotate_columns
from ..superset_client import create_editor_url, create_guest_token
from ..temporal_activities import run_agent_plan_locally
from ..extraction_runtime import run_external_extraction_now
from ..temporal_runtime import cancel_workflow, start_agent_workflow, start_external_extraction_workflow, start_metadata_scan_workflow, start_scheduled_ingestion_workflow
from ..tool_runtime import ToolRuntimeError, execute_tool
from ..vector_store import index_document, search_documents
from fastapi import APIRouter

from .. import core as main
from ..core import (
    AGENT_APPROVAL_KEYWORDS, AgentDefinition, AgentDefinitionCreate,
    AgentDefinitionUpdate, AgentRunRequest, AgentVersion, AgentVersionCreate, Any,
    Approval, ApprovalDecision, Artifact, ArtifactComment, ArtifactCommentCreate,
    ArtifactCreate, ArtifactReviewRequest, ArtifactVersion, AuditEvent, AuthProvider,
    AuthProviderUpdate, Base, BaseModel, CORSMiddleware, ConfigDict, Connector,
    ConnectorCreate, ConnectorRuntimeError, ConnectorUpdate, Conversation,
    ConversationAsk, ConversationCreate, ConversationMessage, ConversationReportCreate,
    DEFAULT_ARTIFACT_TARGETS, DataAsset, Depends, EvaluationBaselineRequest,
    EvaluationCaseInput, EvaluationRun, EvaluationRunRequest, EvaluationSet,
    EvaluationSetCreate, ExternalClient, ExternalClientCreate, ExternalClientUpdate,
    ExternalExtraction, ExternalExtractionCreate, ExternalInvocation, FastAPI,
    FeedbackCreate, Field, File, FileStageRequest, Form, HTTPException, Header,
    Incident, IncidentResolveRequest, IngestedFile, IngestionMapping,
    IngestionSchedule, Job, LearningSuggestion, LearningSuggestionReview, LineageEdge,
    Literal, LoginRequest, MCPRequest, MappingColumn, ModelCallLog, ModelProvider,
    NotebookCell, NotebookSave, ORMModel, PasswordChange, Path, PipelineDefinition,
    PipelineGenerateRequest, PipelineGenerationError,
    PipelinePackageDeliveryConfigSave, PipelinePackageSummary, PipelineUpdateRequest,
    PipelineVersion, Project, ProjectCreate, ProjectMemberUpdate, ProjectMembership,
    ProjectModelUpdate, PromptRollback, PromptSave, ProviderCreate, ProviderUpdate,
    QualityRemediationRequest, QualityRule, QualityRuleCreate, QualityRun, Query,
    QueryTool, QueryToolCreate, QueryToolGrant, QueryToolGrantCreate, QueryToolInvoke,
    QueryToolWizardPreview, RedTeamSuiteCreate, Request, RetentionPolicy,
    RetentionPolicySave, SECURITY_CATEGORIES, SECURITY_CATEGORY_LABELS,
    SECURITY_SEVERITIES, SQLExecutionRequest, SQLQueryCache, SQLRequest,
    ScheduleCreate, SchemaDriftEvent, SchemaMappingCreate, SemanticJoinPolicy,
    SemanticJoinPolicyCreate, SemanticMetric, SemanticMetricCreate, Session,
    SessionLocal, StreamingResponse, SupersetProjectDashboard, ToolDefinition,
    ToolDefinitionCreate, ToolDefinitionUpdate, ToolExecuteRequest, ToolExecution,
    ToolRuntimeError, ToolVersion, ToolVersionCreate, UPLOAD_DIR, UploadFile, User,
    UserCreate, UserFeedback, UserUpdate, _asset_relation_sql, _build_delivery_plan,
    _build_pipeline_package_or_404, _cached_sql_response, _catalog_sql_context,
    _chart_from_result, _default_delivery_config, _delivery_config_for_target,
    _external_client_from_header, _external_query_tool_output, _extract_sql,
    _filter_registry_tools, _get_project_pipeline_with_version, _granted_query_tools,
    _identifier_quote, _invoke_external_query_tool, _json_schema_type,
    _local_execution_error, _normalize_delivery_config, _registry_metadata,
    _safe_read_only_sql, _security_bucket_label, _security_category_from_incident,
    _security_posture, _security_score, _security_text, _sql_cache_key,
    _store_sql_query_cache, _superset_dataset, _validate_connector_contract,
    _validate_query_tool_contract, _validate_tool_parameters,
    agent_run_requires_approval, analysis_source_output, annotations, as_dict,
    asynccontextmanager, asyncio, audit, backfill_project_columns,
    build_exported_package, cancel_workflow, column_names_for_asset,
    compact_conversation_context, connector_dialect, connector_output,
    context_signature, conversation_output, conversational_analysis_answer,
    create_access_token, create_editor_url, create_guest_token, create_package_archive,
    create_quality_rule_record, dataset_category, datetime, delete, elapsed_ms, emit,
    emit_pipeline_artifacts, engine, ensure_demo_tables, ensure_project_columns,
    estimated_model_cost, execute_metadata_scan, execute_notebook,
    execute_parameterized_read_only, execute_quality_rule, execute_read_only,
    execute_tool, external_client_output, external_extraction_columns,
    external_extraction_output, func, generate_text, generated_catalog_sql,
    generated_sql, get_current_user, get_db, grounding_context, grounding_prompt_text,
    hash_password, hashlib, httpx, index_document, initial_agent_plan,
    initialize_governance, initialize_observability, inspect, invoke_provider_test, io,
    json, next_run_at, normalize_query, observability_status, os, pipeline_output,
    plan_pipeline, profile_file, project_grounding_signature, project_output,
    quality_rule_output, query_tool_output, query_tool_usage_summary, re,
    read_structured_rows, record_audit_event, refresh_conversation_summary, request_id,
    require_admin, require_current_project, require_data_editor,
    require_project_resource, require_role, require_semantic_maintainer,
    require_workspace_editor, resolve_superset_dataset, run_agent_evaluation_case,
    run_agent_plan_locally, run_ingestion_schedule, safe_identifier,
    save_internal_artifact_version, save_superset_dashboard_state, schedule_output,
    search_documents, secrets, seed_database, select, selected_model_provider,
    semantic_join_policy_output, session_user_output, shutil, span, stage_rows,
    start_agent_workflow, start_metadata_scan_workflow,
    start_scheduled_ingestion_workflow, test_connection, text, time, timedelta,
    timezone, unified_diff, uuid4, validate_exported_package,
    validate_pipeline_artifacts, validate_pipeline_spec, validate_semantic_join_policy,
    verify_password,
)

router = APIRouter()


@router.get("/files")
def list_files(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    files = db.scalars(
        select(IngestedFile).where(IngestedFile.project_id == project.id).order_by(IngestedFile.created_at.desc())
    ).all()
    return [
        as_dict(
            item,
            ["id", "filename", "content_type", "size_bytes", "status", "row_count", "profile", "created_at"],
        )
        for item in files
    ]

@router.post("/files/ingest", status_code=201)
def ingest_file(
    file: UploadFile = File(...),
    stage_to_postgres: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    suffix = Path(file.filename or "").suffix.lower()
    allowed = {".csv", ".json", ".xlsx", ".parquet", ".pdf"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Supported file types: {', '.join(sorted(allowed))}")
    stored_name = f"{uuid4()}{suffix}"
    destination = UPLOAD_DIR / stored_name
    with destination.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    profile = profile_file(destination, suffix)
    item = IngestedFile(
        id=str(uuid4()),
        project_id=project.id,
        filename=file.filename or stored_name,
        content_type=file.content_type,
        size_bytes=destination.stat().st_size,
        storage_path=str(destination),
        status="profiling",
        row_count=profile.get("row_count"),
        profile=profile,
        created_by=user.id,
    )
    staged: dict[str, Any] | None = None
    if profile.get("kind") == "structured":
        if stage_to_postgres:
            rows = read_structured_rows(destination, suffix) or []
            staged = stage_rows(
                engine,
                Path(item.filename).stem,
                item.id,
                profile.get("columns", []),
                rows,
            )
            profile = {**profile, "staged_table": staged}
            item.profile = profile
            item.status = "staged"
        else:
            item.status = "profiled"
        table_name = staged["table_name"] if staged else safe_identifier(Path(item.filename).stem, f"file_{item.id[:8]}")
        schema_name = staged["schema_name"] if staged else "file_profiles"
        db.add(
            DataAsset(
                project_id=project.id,
                source_name="Local files",
                schema_name=schema_name,
                table_name=table_name,
                asset_type="staged_file",
                row_count=profile.get("row_count"),
                columns=annotate_columns(
                    (
                    [
                        {"name": column["name"], "type": column["type"], "nullable": True}
                        for column in staged["columns"]
                    ]
                    if staged
                    else [
                        {
                            "name": column["name"],
                            "type": column["inferred_type"],
                            "nullable": column["null_count"] > 0,
                        }
                        for column in profile.get("columns", [])
                    ]
                    )
                ),
                tags=["local-file", item.status],
                description=f"Ingested from {item.filename}",
            )
        )
    else:
        item.status = "indexed"
    db.add(item)
    audit(db, user, "file.ingested", "file", item.id, {"filename": item.filename, "status": item.status})
    db.commit()
    db.refresh(item)
    try:
        knowledge_text = profile.get("preview") or (
            f"Structured file with {profile.get('row_count', 0)} rows. Columns: "
            + ", ".join(column.get("name", "") for column in profile.get("columns", []))
        )
        index_document(
            item.id,
            item.filename,
            knowledge_text,
            {
                "source_type": "file",
                "status": item.status,
                "relation": staged.get("relation") if staged else None,
            },
            db=db,
        )
    except Exception:
        pass
    return as_dict(item, ["id", "filename", "size_bytes", "status", "row_count", "profile", "created_at"])

@router.get("/files/{file_id}/mappings")
def list_file_mappings(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    require_project_resource(db.get(IngestedFile, file_id), project, "File")
    mappings = db.scalars(
        select(IngestionMapping)
        .where(IngestionMapping.file_id == file_id, IngestionMapping.project_id == project.id)
        .order_by(IngestionMapping.updated_at.desc())
    ).all()
    return [
        as_dict(
            mapping,
            [
                "id",
                "file_id",
                "name",
                "target_schema",
                "target_table",
                "columns",
                "latest_relation",
                "run_count",
                "artifact_id",
                "created_at",
                "updated_at",
            ],
        )
        for mapping in mappings
    ]

@router.get("/ingestion-mappings")
def list_ingestion_mappings(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    mappings = db.scalars(
        select(IngestionMapping).where(IngestionMapping.project_id == project.id).order_by(IngestionMapping.updated_at.desc())
    ).all()
    return [
        {
            **as_dict(mapping, ["id", "file_id", "name", "target_table", "columns", "latest_relation", "run_count", "updated_at"]),
            "filename": (db.get(IngestedFile, mapping.file_id).filename if db.get(IngestedFile, mapping.file_id) else "missing file"),
        }
        for mapping in mappings
    ]

@router.get("/external-extractions")
def list_external_extractions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    extractions = db.scalars(
        select(ExternalExtraction)
        .where(ExternalExtraction.project_id == project.id)
        .order_by(ExternalExtraction.updated_at.desc())
    ).all()
    return [external_extraction_output(extraction, db) for extraction in extractions]

@router.post("/external-extractions", status_code=201)
def create_external_extraction(
    payload: ExternalExtractionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(user, db)
    project = require_current_project(db, user)
    connector = require_project_resource(db.get(Connector, payload.connector_id), project, "Connector")
    asset = require_project_resource(db.get(DataAsset, payload.source_asset_id), project, "Data asset")
    if connector.connection_mode != "direct":
        raise HTTPException(status_code=409, detail="External extraction currently requires a certified direct connector")
    if not connector.read_only:
        raise HTTPException(status_code=409, detail="External extraction requires a read-only source connector")
    if asset.connector_id != connector.id:
        raise HTTPException(status_code=400, detail="The source asset must belong to the selected connector")
    source_columns = {str(column.get("name")) for column in asset.columns}
    if not source_columns:
        raise HTTPException(status_code=409, detail="The source asset has no scanned columns")
    if payload.watermark_column and payload.watermark_column not in source_columns:
        raise HTTPException(status_code=400, detail="The watermark column is not part of the source asset")
    if payload.load_mode == "upsert" and not payload.key_columns:
        raise HTTPException(status_code=400, detail="Merge extraction requires at least one key column")
    if any(key not in source_columns for key in payload.key_columns):
        raise HTTPException(status_code=400, detail="An extraction key column is not part of the source asset")
    target_table = safe_identifier(payload.target_table, "external_extract")
    extraction = ExternalExtraction(
        project_id=project.id,
        connector_id=connector.id,
        source_asset_id=asset.id,
        name=payload.name,
        target_table=target_table,
        load_mode=payload.load_mode,
        key_columns=[safe_identifier(key, "key") for key in payload.key_columns],
        watermark_column=payload.watermark_column,
        batch_limit=payload.batch_limit,
        created_by=user.id,
    )
    db.add(extraction)
    db.flush()
    artifact, _ = save_internal_artifact_version(
        db,
        user,
        f"External extraction: {payload.name}",
        "workflow",
        json.dumps(
            {
                "connector_id": connector.id,
                "source_asset_id": asset.id,
                "source_relation": f"{asset.schema_name}.{asset.table_name}",
                "target_table": target_table,
                "load_mode": payload.load_mode,
                "key_columns": extraction.key_columns,
                "watermark_column": payload.watermark_column,
                "batch_limit": payload.batch_limit,
            },
            indent=2,
        ),
        {"external_extraction_id": extraction.id, "state": "draft"},
    )
    extraction.artifact_id = artifact.id
    audit(db, user, "external_extraction.created", "external_extraction", extraction.id, {"connector_id": connector.id, "source_asset_id": asset.id})
    db.commit()
    return external_extraction_output(extraction, db)

@router.post("/external-extractions/{extraction_id}/run", status_code=202)
async def run_external_extraction(
    extraction_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Pull one bounded batch from a source connector into local staging.

    Tries a Temporal-backed durable/retryable run first (same pattern as
    POST /schedules/{id}/run), falling back to running synchronously inline
    when TEMPORAL_ADDRESS isn't configured. Previously this endpoint only
    ever ran synchronously, blocking the request thread for the query
    duration with no durability or retry -- the one ingestion path that
    hadn't gotten the async treatment already given to metadata scans and
    scheduled file ingestion. See extraction_runtime.py and
    IMPLEMENTATION_STATUS_MATRIX.md for the full write-up.
    """
    require_data_editor(user, db)
    project = require_current_project(db, user)
    extraction = require_project_resource(db.get(ExternalExtraction, extraction_id), project, "External extraction")
    connector = require_project_resource(db.get(Connector, extraction.connector_id), project, "Connector")
    require_project_resource(db.get(DataAsset, extraction.source_asset_id), project, "Data asset")
    if connector.connection_mode != "direct" or not connector.read_only:
        raise HTTPException(status_code=409, detail="The extraction source must remain a read-only direct connector")
    resolved_extraction_id = extraction.id
    resolved_user_id = user.id
    db.close()
    workflow_id = await start_external_extraction_workflow(resolved_extraction_id, resolved_user_id)
    if workflow_id:
        return {"status": "QUEUED", "workflow_id": workflow_id}
    try:
        result = run_external_extraction_now(resolved_extraction_id, resolved_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"External extraction failed: {exc}") from exc
    return {**result, "workflow_id": None}

@router.get("/schedules")
def list_schedules(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    schedules = db.scalars(
        select(IngestionSchedule).where(IngestionSchedule.project_id == project.id).order_by(IngestionSchedule.created_at.desc())
    ).all()
    return [schedule_output(schedule, db) for schedule in schedules]

@router.post("/schedules", status_code=201)
def create_schedule(
    payload: ScheduleCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(user, db)
    project = require_current_project(db, user)
    mapping = require_project_resource(db.get(IngestionMapping, payload.mapping_id), project, "Ingestion mapping")
    target_columns = {str(column["target_name"]) for column in mapping.columns}
    if payload.watermark_column and payload.watermark_column not in target_columns:
        raise HTTPException(status_code=400, detail="Watermark column is not in the mapping")
    if payload.load_mode == "upsert" and not payload.key_columns:
        raise HTTPException(status_code=400, detail="Merge schedules require key columns")
    if any(key not in target_columns for key in payload.key_columns):
        raise HTTPException(status_code=400, detail="A schedule key column is not in the mapping")
    try:
        due_at = next_run_at(payload.cron)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    schedule = IngestionSchedule(
        project_id=project.id,
        **payload.model_dump(),
        enabled=False,
        next_run_at=due_at,
        created_by=user.id,
    )
    db.add(schedule)
    db.flush()
    job = Job(
        project_id=project.id,
        title=f"Approve schedule: {schedule.name}",
        job_type="schedule_creation",
        status="WAITING_FOR_APPROVAL",
        progress=70,
        created_by=user.id,
        plan=[
            {"agent": "Pipeline", "action": "Validate mapping and load mode", "status": "complete"},
            {"agent": "Policy", "action": "Approve recurring execution", "status": "waiting"},
        ],
        evidence=[
            {"type": "mapping", "label": mapping.name},
            {"type": "schedule", "label": payload.cron},
        ],
    )
    db.add(job)
    db.flush()
    approval = Approval(
        project_id=project.id,
        job_id=job.id,
        title=f"Enable ingestion schedule: {schedule.name}",
        action_type="enable_ingestion_schedule",
        risk_level="medium",
        requested_by=user.id,
        evidence={
            "summary": f"Run {mapping.name} on {schedule.cron} using {schedule.load_mode}",
            "checks": ["local execution", "approved mapping", "read-only source", "audited target writes"],
            "schedule_id": schedule.id,
        },
    )
    db.add(approval)
    definition = {
        "kind": "scheduled_ingestion",
        "schedule_id": schedule.id,
        "mapping_id": mapping.id,
        **payload.model_dump(),
    }
    save_internal_artifact_version(
        db,
        user,
        f"Schedule {schedule.name}",
        "workflow",
        json.dumps(definition, indent=2),
        {"schedule_id": schedule.id, "state": "awaiting_approval"},
    )
    audit(db, user, "schedule.requested", "ingestion_schedule", schedule.id, {"approval_id": approval.id})
    db.commit()
    return {**schedule_output(schedule, db), "approval_id": approval.id, "job_id": job.id}

@router.post("/schedules/{schedule_id}/run", status_code=202)
async def run_schedule_now(
    schedule_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(user, db)
    project = require_current_project(db, user)
    schedule = require_project_resource(db.get(IngestionSchedule, schedule_id), project, "Ingestion schedule")
    if not schedule.enabled:
        raise HTTPException(status_code=409, detail="Approve the schedule before running it")
    resolved_schedule_id = schedule.id
    resolved_user_id = user.id
    db.commit()
    workflow_id = await start_scheduled_ingestion_workflow(resolved_schedule_id, resolved_user_id)
    if workflow_id:
        audit(db, user, "schedule.run_queued", "ingestion_schedule", resolved_schedule_id, {"workflow_id": workflow_id})
        db.commit()
        return {"status": "QUEUED", "workflow_id": workflow_id}
    db.close()
    result = run_ingestion_schedule(resolved_schedule_id, resolved_user_id)
    return {**result, "workflow_id": None}

@router.post("/schedules/{schedule_id}/disable")
def disable_schedule(
    schedule_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(user, db)
    project = require_current_project(db, user)
    schedule = require_project_resource(db.get(IngestionSchedule, schedule_id), project, "Ingestion schedule")
    schedule.enabled = False
    audit(db, user, "schedule.disabled", "ingestion_schedule", schedule.id)
    db.commit()
    return schedule_output(schedule, db)

@router.post("/files/{file_id}/schema", status_code=201)
def save_file_schema(
    file_id: str,
    payload: SchemaMappingCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    item = require_project_resource(db.get(IngestedFile, file_id), project, "File")
    if item.profile.get("kind") != "structured":
        raise HTTPException(status_code=409, detail="Only structured files support schema mappings")
    available = {str(column["name"]) for column in item.profile.get("columns", [])}
    requested_sources = [column.source_name for column in payload.columns]
    if any(source not in available for source in requested_sources):
        raise HTTPException(status_code=400, detail="A mapped source column does not exist in the file")
    target_names = [safe_identifier(column.target_name, "column") for column in payload.columns]
    if len(target_names) != len(set(target_names)):
        raise HTTPException(status_code=400, detail="Mapped target column names must be unique")

    mapping = db.get(IngestionMapping, payload.mapping_id) if payload.mapping_id else None
    if mapping and mapping.file_id != item.id:
        raise HTTPException(status_code=409, detail="The mapping belongs to a different file")
    target_table = safe_identifier(payload.target_table, f"file_{item.id[:8]}")
    columns = [column.model_dump() for column in payload.columns]
    if mapping is None:
        mapping = IngestionMapping(
            project_id=project.id,
            file_id=item.id,
            name=payload.name,
            target_table=target_table,
            columns=columns,
            created_by=user.id,
        )
        db.add(mapping)
        db.flush()
    else:
        mapping.name = payload.name
        mapping.target_table = target_table
        mapping.columns = columns
        mapping.updated_at = datetime.now(timezone.utc)

    workflow = {
        "kind": "local_file_ingestion",
        "source_file_id": item.id,
        "source_filename": item.filename,
        "target": f"staging.{target_table}",
        "columns": columns,
        "steps": ["read source", "apply column mapping", "coerce types", "stage rows", "index metadata"],
    }
    artifact, version = save_internal_artifact_version(
        db,
        user,
        f"Ingest {item.filename} to staging.{target_table}",
        "workflow",
        json.dumps(workflow, indent=2),
        {"mapping_id": mapping.id, "file_id": item.id, "state": "confirmed"},
        mapping.artifact_id,
    )
    mapping.artifact_id = artifact.id
    item.profile = {
        **item.profile,
        "confirmed_mapping": {
            "id": mapping.id,
            "name": mapping.name,
            "target_table": mapping.target_table,
            "columns": mapping.columns,
        },
    }
    audit(db, user, "file.schema_confirmed", "ingestion_mapping", mapping.id, {"version": version.version})
    db.commit()
    return {
        **as_dict(
            mapping,
            ["id", "file_id", "name", "target_schema", "target_table", "columns", "latest_relation", "run_count", "artifact_id"],
        ),
        "artifact_version": version.version,
    }

@router.post("/files/{file_id}/stage", status_code=201)
def stage_file_mapping(
    file_id: str,
    payload: FileStageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    item = require_project_resource(db.get(IngestedFile, file_id), project, "File")
    mapping = require_project_resource(db.get(IngestionMapping, payload.mapping_id), project, "File mapping")
    if mapping.file_id != item.id:
        raise HTTPException(status_code=404, detail="File mapping not found")
    suffix = Path(item.filename).suffix.lower()
    rows = read_structured_rows(Path(item.storage_path), suffix)
    if rows is None:
        raise HTTPException(status_code=409, detail="The file is no longer available as structured data")
    try:
        staged = stage_rows(
            engine,
            mapping.target_table,
            item.id,
            mapping.columns,
            rows,
            load_mode=payload.load_mode,
            key_columns=payload.key_columns,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item.status = "staged"
    item.profile = {
        **item.profile,
        "staged_table": staged,
        "confirmed_mapping": {
            "id": mapping.id,
            "name": mapping.name,
            "target_table": mapping.target_table,
            "columns": mapping.columns,
            "load_mode": payload.load_mode,
            "key_columns": payload.key_columns,
        },
    }
    mapping.latest_relation = staged["relation"]
    mapping.run_count += 1
    mapping.updated_at = datetime.now(timezone.utc)
    asset = db.scalar(
        select(DataAsset).where(
            DataAsset.project_id == project.id,
            DataAsset.source_name == "Local files",
            DataAsset.schema_name == staged["schema_name"],
            DataAsset.table_name == staged["table_name"],
        )
    )
    if asset is None:
        asset = DataAsset(
            project_id=project.id,
            source_name="Local files",
            schema_name=staged["schema_name"],
            table_name=staged["table_name"],
            asset_type="staged_file",
        )
        db.add(asset)
    asset.row_count = staged["row_count"]
    asset.columns = [
            {
                "name": column["name"],
                "type": column["type"],
                "nullable": next(
                    (mapped["nullable"] for mapped in mapping.columns if mapped["source_name"] == column["source_name"]),
                    True,
                ),
            }
            for column in staged["columns"]
        ]
    asset.tags = ["local-file", "mapped", "staged", payload.load_mode]
    asset.description = f"Mapped {payload.load_mode} ingestion from {item.filename}"
    db.flush()
    job = Job(
        project_id=project.id,
        title=f"Stage {item.filename} to {staged['relation']}",
        job_type="file_ingestion",
        status="SUCCEEDED",
        progress=100,
        plan=[
            {"agent": "Profile", "action": "Read source file", "status": "complete"},
            {"agent": "Mapping", "action": "Apply confirmed schema", "status": "complete"},
            {"agent": "Runner", "action": "Write PostgreSQL staging relation", "status": "complete"},
            {"agent": "Metadata", "action": "Publish catalog context", "status": "complete"},
        ],
        evidence=[
            {"type": "file", "label": item.filename},
            {"type": "mapping", "label": mapping.name},
            {"type": "dataset", "label": staged["relation"]},
        ],
        logs=[{"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Loaded {staged['loaded_rows']} rows using {payload.load_mode}; target contains {staged['row_count']} rows"}],
        created_by=user.id,
    )
    db.add(job)
    workflow = {
        "kind": "local_file_ingestion",
        "mapping_id": mapping.id,
        "source_file_id": item.id,
        "target_relation": staged["relation"],
        "row_count": staged["row_count"],
        "columns": mapping.columns,
        "run": mapping.run_count,
        "load_mode": payload.load_mode,
        "key_columns": payload.key_columns,
    }
    artifact, version = save_internal_artifact_version(
        db,
        user,
        f"Ingest {item.filename} to staging.{mapping.target_table}",
        "workflow",
        json.dumps(workflow, indent=2),
        {"mapping_id": mapping.id, "file_id": item.id, "state": "executed", "relation": staged["relation"]},
        mapping.artifact_id,
    )
    mapping.artifact_id = artifact.id
    audit(db, user, "file.mapping_executed", "ingestion_mapping", mapping.id, {"relation": staged["relation"], "job_id": job.id})
    db.commit()
    try:
        index_document(
            asset.id,
            staged["relation"],
            f"Mapped local file {item.filename} with {staged['row_count']} rows. Columns: "
            + ", ".join(column["name"] for column in staged["columns"]),
            {"source_type": "dataset", "schema_name": staged["schema_name"], "table_name": staged["table_name"], "tags": asset.tags},
            db=db,
        )
    except Exception:
        pass
    return {
        **as_dict(item, ["id", "filename", "size_bytes", "status", "row_count", "profile", "created_at"]),
        "mapping": as_dict(mapping, ["id", "name", "latest_relation", "run_count", "artifact_id"]),
        "job_id": job.id,
        "artifact_version": version.version,
        "asset_id": asset.id,
    }
