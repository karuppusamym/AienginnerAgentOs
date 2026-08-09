"""Auto-extracted connectors routes from the former monolithic main.py.

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
from ..superset_client import create_editor_url, create_guest_token
from ..temporal_activities import run_agent_plan_locally
from ..temporal_runtime import cancel_workflow, start_agent_workflow, start_metadata_scan_workflow, start_scheduled_ingestion_workflow
from ..tool_runtime import ToolRuntimeError, execute_tool
from ..vector_store import index_document, search_documents
from fastapi import APIRouter

from .. import main
from ..main import (
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
    agent_run_requires_approval, analysis_source_output, annotations, app,
    app_lifespan, as_dict, asynccontextmanager, asyncio, audit,
    backfill_project_columns, build_exported_package, cancel_workflow,
    column_names_for_asset, compact_conversation_context, connector_dialect,
    connector_output, context_signature, conversation_output,
    conversational_analysis_answer, create_access_token, create_editor_url,
    create_guest_token, create_package_archive, create_quality_rule_record,
    dataset_category, datetime, delete, elapsed_ms, emit, emit_pipeline_artifacts,
    engine, ensure_demo_tables, ensure_project_columns, estimated_model_cost,
    execute_metadata_scan, execute_notebook, execute_parameterized_read_only,
    execute_quality_rule, execute_read_only, execute_tool, external_client_output,
    external_extraction_columns, external_extraction_output, func, generate_text,
    generated_catalog_sql, generated_sql, get_current_user, get_db, grounding_context,
    grounding_prompt_text, hash_password, hashlib, httpx, index_document,
    initial_agent_plan, initialize_governance, initialize_observability, inspect,
    invoke_provider_test, io, json, next_run_at, normalize_query, observability_status,
    observe_request, os, pipeline_output, plan_pipeline, profile_file,
    project_grounding_signature, project_output, quality_rule_output,
    query_tool_output, query_tool_usage_summary, re, read_structured_rows,
    record_audit_event, refresh_conversation_summary, request_id, require_admin,
    require_current_project, require_data_editor, require_project_resource,
    require_role, require_semantic_maintainer, require_workspace_editor,
    resolve_superset_dataset, run_agent_evaluation_case, run_agent_plan_locally,
    run_ingestion_schedule, safe_identifier, save_internal_artifact_version,
    save_superset_dashboard_state, schedule_output, search_documents, secrets,
    seed_database, select, selected_model_provider, semantic_join_policy_output,
    session_user_output, shutil, span, stage_rows, start_agent_workflow,
    start_metadata_scan_workflow, start_scheduled_ingestion_workflow, startup,
    test_connection, text, time, timedelta, timezone, unified_diff, uuid4,
    validate_exported_package, validate_pipeline_artifacts, validate_pipeline_spec,
    validate_semantic_join_policy, verify_password,
)

router = APIRouter()


@router.get("/connectors")
def list_connectors(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    connectors = db.scalars(
        select(Connector).where(Connector.project_id == project.id).order_by(Connector.created_at)
    ).all()
    return [connector_output(connector, include_secret=user.role in {"admin", "engineer"}) for connector in connectors]

@router.post("/connectors", status_code=201)
def create_connector(
    payload: ConnectorCreate,
    admin: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(admin)
    project = require_current_project(db, admin)
    if not payload.read_only:
        raise HTTPException(status_code=400, detail="DataPilot connectors must be read-only")
    _validate_connector_contract(payload)
    connector = Connector(project_id=project.id, **payload.model_dump(), status="not_tested")
    db.add(connector)
    db.flush()
    audit(db, admin, "connector.created", "connector", connector.id)
    db.commit()
    db.refresh(connector)
    return connector_output(connector, include_secret=True)

@router.put("/connectors/{connector_id}")
def update_connector(
    connector_id: str,
    payload: ConnectorUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(user)
    project = require_current_project(db, user)
    connector = require_project_resource(db.get(Connector, connector_id), project, "Connector")
    if not payload.read_only:
        raise HTTPException(status_code=400, detail="DataPilot connectors must be read-only")
    _validate_connector_contract(payload)
    for field, value in payload.model_dump().items():
        setattr(connector, field, value)
    connector.status = "not_tested"
    audit(db, user, "connector.updated", "connector", connector.id)
    db.commit()
    db.refresh(connector)
    return connector_output(connector, include_secret=True)

@router.delete("/connectors/{connector_id}")
def delete_connector(
    connector_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_data_editor(user)
    project = require_current_project(db, user)
    connector = require_project_resource(db.get(Connector, connector_id), project, "Connector")
    asset_count = db.scalar(select(func.count()).select_from(DataAsset).where(DataAsset.connector_id == connector.id)) or 0
    if asset_count:
        raise HTTPException(status_code=409, detail="Connector has catalog datasets; remove dependent assets before deleting it")
    db.delete(connector)
    audit(db, user, "connector.deleted", "connector", connector_id)
    db.commit()
    return {"status": "deleted"}

@router.post("/connectors/{connector_id}/test")
def test_connector(
    connector_id: str,
    admin: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(admin)
    project = require_current_project(db, admin)
    connector = require_project_resource(db.get(Connector, connector_id), project, "Connector")
    try:
        result = test_connection(connector)
        connector.status = result.status
        audit(
            db,
            admin,
            "connector.tested",
            "connector",
            connector.id,
            {"status": connector.status, "latency_ms": result.latency_ms},
        )
        db.commit()
        return {
            "status": result.status,
            "message": result.message,
            "latency_ms": result.latency_ms,
        }
    except ConnectorRuntimeError as exc:
        connector.status = "error"
        audit(
            db,
            admin,
            "connector.test_failed",
            "connector",
            connector.id,
            {"error": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/connectors/{connector_id}/scan")
async def scan_connector(
    connector_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(user)
    project = require_current_project(db, user)
    connector = require_project_resource(db.get(Connector, connector_id), project, "Connector")
    job = Job(
        project_id=project.id,
        title=f"Metadata scan: {connector.name}",
        job_type="metadata_scan",
        status="QUEUED",
        progress=5,
        created_by=user.id,
        plan=[
            {"agent": "Metadata", "action": "Test read-only access", "status": "waiting"},
            {"agent": "Metadata", "action": "Enumerate schemas and tables", "status": "pending"},
            {"agent": "Policy", "action": "Classify sensitive columns", "status": "pending"},
        ],
        evidence=[{"type": "connector", "label": connector.name}],
        logs=[
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "level": "info",
                "message": "Metadata discovery queued",
            }
        ],
    )
    db.add(job)
    db.flush()
    connector_id_value = connector.id
    job_id = job.id
    actor_id = user.id
    current_summary = connector.metadata_summary or {"schemas": 0, "tables": 0, "columns": 0}
    db.commit()
    try:
        workflow_id = await start_metadata_scan_workflow(connector_id_value, job_id, actor_id)
        if workflow_id:
            return {"status": "QUEUED", "summary": current_summary, "job_id": job_id, "assets_discovered": 0, "workflow_id": workflow_id}
        db.close()
        return {**execute_metadata_scan(connector_id_value, job_id, actor_id), "workflow_id": None}
    except ConnectorRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/schema-drift")
def list_schema_drift(status: str | None = Query(default=None), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    statement = select(SchemaDriftEvent).where(SchemaDriftEvent.project_id == project.id).order_by(SchemaDriftEvent.detected_at.desc())
    if status:
        statement = statement.where(SchemaDriftEvent.status == status)
    events = db.scalars(statement.limit(200)).all()
    return [as_dict(item, ["id", "project_id", "connector_id", "asset_id", "relation", "changes", "status", "detected_at", "acknowledged_by", "acknowledged_at"]) for item in events]

@router.post("/schema-drift/{event_id}/acknowledge")
def acknowledge_schema_drift(event_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    project = require_current_project(db, user)
    event = db.get(SchemaDriftEvent, event_id)
    if event is None or event.project_id != project.id:
        raise HTTPException(status_code=404, detail="Schema drift event not found")
    event.status = "acknowledged"
    event.acknowledged_by = user.id
    event.acknowledged_at = datetime.now(timezone.utc)
    audit(db, user, "schema_drift.acknowledged", "schema_drift", event.id)
    db.commit()
    return as_dict(event, ["id", "relation", "changes", "status", "detected_at", "acknowledged_by", "acknowledged_at"])
