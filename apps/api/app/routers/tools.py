"""Auto-extracted tools routes from the former monolithic main.py.

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


@router.get("/tools")
def list_tools(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    tools = db.scalars(select(ToolDefinition).order_by(ToolDefinition.category, ToolDefinition.name)).all()
    output = []
    for tool in tools:
        latest = db.scalar(select(ToolVersion).where(ToolVersion.tool_id == tool.id).order_by(ToolVersion.version.desc()).limit(1))
        output.append({**as_dict(tool, ["id", "name", "category", "description", "risk_level", "enabled", "requires_approval"]), "current_version": latest.version if latest else 0, "version_status": latest.status if latest else "unversioned", "implementation_type": latest.implementation_type if latest else None, "parameter_schema": latest.parameter_schema if latest else {}})
    return output

@router.post("/tools", status_code=201)
def create_tool(payload: ToolDefinitionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    if db.scalar(select(ToolDefinition).where(ToolDefinition.name == payload.name)):
        raise HTTPException(status_code=409, detail="A tool with this name already exists")
    if payload.implementation_type == "builtin":
        raise HTTPException(status_code=400, detail="Built-in handlers can only be registered by the backend")
    # A high/critical-risk tool must always require approval before it can
    # execute — risk_level and requires_approval were previously independent
    # fields with nothing enforcing they agree, so any admin/engineer could
    # register a "critical" risk tool with requires_approval=False and it
    # would run immediately and synchronously with zero Approval ever
    # created. Force the invariant server-side instead of trusting the caller.
    requires_approval = payload.requires_approval or payload.risk_level in {"high", "critical"}
    tool = ToolDefinition(name=payload.name, category=payload.category, description=payload.description, risk_level=payload.risk_level, enabled=payload.enabled, requires_approval=requires_approval)
    db.add(tool)
    db.flush()
    version_fields = payload.model_dump(exclude={"name", "category", "description", "risk_level", "enabled", "requires_approval"})
    version = ToolVersion(tool_id=tool.id, version=1, status="draft", created_by=user.id, **version_fields)
    db.add(version)
    audit(db, user, "tool.created", "tool", tool.id, {"version": 1})
    db.commit()
    return {**as_dict(tool, ["id", "name", "category", "description", "risk_level", "enabled", "requires_approval"]), "current_version": 1, "version_status": "draft"}

@router.get("/tools/executions")
def list_tool_executions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    executions = db.scalars(select(ToolExecution).where(ToolExecution.project_id == project.id).order_by(ToolExecution.created_at.desc()).limit(100)).all()
    return [as_dict(item, ["id", "project_id", "tool_id", "tool_version", "job_id", "status", "parameters", "result", "error", "attempt_count", "duration_ms", "created_by", "created_at", "completed_at"]) for item in executions]

@router.get("/tools/{tool_id}")
def get_tool(tool_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    tool = db.get(ToolDefinition, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    versions = db.scalars(select(ToolVersion).where(ToolVersion.tool_id == tool.id).order_by(ToolVersion.version.desc())).all()
    return {**as_dict(tool, ["id", "name", "category", "description", "risk_level", "enabled", "requires_approval"]), "versions": [as_dict(version, ["id", "version", "implementation_type", "handler_name", "endpoint", "http_method", "parameter_schema", "result_schema", "permissions", "timeout_seconds", "max_retries", "retry_backoff_seconds", "cost_class", "environment", "status", "created_by", "created_at"]) for version in versions]}

@router.put("/tools/{tool_id}")
def update_tool(tool_id: str, payload: ToolDefinitionUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    tool = db.get(ToolDefinition, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    updates = payload.model_dump()
    effective_risk = updates.get("risk_level", tool.risk_level)
    if effective_risk in {"high", "critical"}:
        # Same invariant as create_tool: a high/critical-risk tool can never
        # be edited into requires_approval=False. Without this, any
        # admin/engineer could PUT an existing tool (including a seeded
        # built-in like pipeline.stage or schedule.run) and silently disable
        # its approval gate going forward.
        updates["requires_approval"] = True
    for field, value in updates.items():
        setattr(tool, field, value)
    audit(db, user, "tool.updated", "tool", tool.id)
    db.commit()
    return as_dict(tool, ["id", "name", "category", "description", "risk_level", "enabled", "requires_approval"])

@router.post("/tools/{tool_id}/versions", status_code=201)
def create_tool_version(tool_id: str, payload: ToolVersionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    tool = db.get(ToolDefinition, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    latest = db.scalar(select(ToolVersion).where(ToolVersion.tool_id == tool.id).order_by(ToolVersion.version.desc()).limit(1))
    if payload.implementation_type == "builtin" and (latest is None or payload.handler_name != latest.handler_name):
        raise HTTPException(status_code=400, detail="Built-in handler bindings cannot be changed through the API")
    next_version = (latest.version if latest else 0) + 1
    version = ToolVersion(tool_id=tool.id, version=next_version, status="draft", created_by=user.id, **payload.model_dump())
    db.add(version)
    audit(db, user, "tool.version_created", "tool", tool.id, {"version": next_version})
    db.commit()
    return as_dict(version, ["id", "version", "implementation_type", "handler_name", "endpoint", "http_method", "parameter_schema", "result_schema", "permissions", "timeout_seconds", "max_retries", "retry_backoff_seconds", "cost_class", "environment", "status", "created_at"])

@router.post("/tools/{tool_id}/versions/{version_number}/publish")
def publish_tool_version(tool_id: str, version_number: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required to publish tools")
    version = db.scalar(select(ToolVersion).where(ToolVersion.tool_id == tool_id, ToolVersion.version == version_number))
    if version is None:
        raise HTTPException(status_code=404, detail="Tool version not found")
    for candidate in db.scalars(select(ToolVersion).where(ToolVersion.tool_id == tool_id)).all():
        if candidate.status == "published":
            candidate.status = "retired"
    version.status = "published"
    audit(db, user, "tool.version_published", "tool", tool_id, {"version": version_number})
    db.commit()
    return {"tool_id": tool_id, "version": version_number, "status": version.status}

@router.post("/tools/{tool_id}/execute", status_code=201)
def run_tool(tool_id: str, payload: ToolExecuteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    tool = db.get(ToolDefinition, tool_id)
    if tool is None or not tool.enabled:
        raise HTTPException(status_code=404, detail="Enabled tool not found")
    version = db.scalar(select(ToolVersion).where(ToolVersion.tool_id == tool.id, ToolVersion.status == "published").order_by(ToolVersion.version.desc()).limit(1))
    if version is None:
        raise HTTPException(status_code=409, detail="Publish a tool version before executing it")
    execution = ToolExecution(project_id=project.id, tool_id=tool.id, tool_version=version.version, status="WAITING_FOR_APPROVAL" if tool.requires_approval else "RUNNING", parameters=payload.parameters, created_by=user.id)
    db.add(execution)
    db.flush()
    if tool.requires_approval:
        job = Job(project_id=project.id, title=f"Execute tool: {tool.name}", job_type="tool_execution", status="WAITING_FOR_APPROVAL", progress=50, plan=[{"agent": "Policy", "action": "Approve parameterized tool execution", "status": "waiting"}], evidence=[{"type": "tool", "label": f"{tool.name} v{version.version}"}], created_by=user.id)
        db.add(job)
        db.flush()
        execution.job_id = job.id
        approval = Approval(project_id=project.id, job_id=job.id, title=f"Execute {tool.name}", action_type="tool_execution", risk_level=tool.risk_level, evidence={"tool_execution_id": execution.id, "summary": tool.description, "checks": ["published version", "validated parameter schema", "audited execution"]}, requested_by=user.id)
        db.add(approval)
        db.commit()
        return {"id": execution.id, "status": execution.status, "job_id": job.id, "approval_id": approval.id}
    started = time.perf_counter()
    try:
        result, attempts, duration_ms = execute_tool(
            db,
            version.implementation_type,
            version.handler_name,
            version.endpoint,
            version.http_method,
            version.parameter_schema,
            payload.parameters,
            project.id,
            version.timeout_seconds,
            version.max_retries,
            version.retry_backoff_seconds,
            user_id=user.id,
            session_id=execution.id,
        )
        execution.status = "SUCCEEDED"
        execution.result = result
        execution.attempt_count = attempts
        execution.duration_ms = duration_ms
    except ToolRuntimeError as exc:
        execution.status = "FAILED"
        execution.error = str(exc)[:5000]
        execution.duration_ms = round((time.perf_counter() - started) * 1000)
    execution.completed_at = datetime.now(timezone.utc)
    audit(db, user, "tool.executed", "tool_execution", execution.id, {"tool": tool.name, "status": execution.status})
    db.commit()
    if execution.status == "FAILED":
        raise HTTPException(status_code=422, detail=execution.error)
    return as_dict(execution, ["id", "tool_id", "tool_version", "status", "parameters", "result", "attempt_count", "duration_ms", "created_at", "completed_at"])
