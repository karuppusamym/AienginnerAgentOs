"""Auto-extracted jobs routes from the former monolithic main.py.

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


@router.get("/jobs")
def list_jobs(
    status: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    statement = select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc())
    if status:
        statuses = [item.strip().upper() for item in status.split(",") if item.strip()]
        statement = statement.where(Job.status.in_(statuses))
    jobs = db.scalars(statement).all()
    return [
        as_dict(job, ["id", "title", "job_type", "status", "progress", "plan", "evidence", "logs", "outputs", "created_at", "updated_at"])
        for job in jobs
    ]

@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    job = require_project_resource(db.get(Job, job_id), project, "Job")
    return as_dict(job, ["id", "title", "job_type", "status", "progress", "plan", "evidence", "logs", "outputs", "created_at", "updated_at"])

@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    job = require_project_resource(db.get(Job, job_id), project, "Job")
    if job.status not in {"DRAFT", "PLANNING", "QUEUED", "RUNNING", "WAITING_FOR_APPROVAL", "RETRYING"}:
        raise HTTPException(status_code=409, detail="This job is already in a terminal state")
    workflow_id = None
    for entry in reversed(job.logs or []):
        match = re.search(r"Temporal workflow ([A-Za-z0-9_.:-]+)", str(entry.get("message", "")))
        if match:
            workflow_id = match.group(1)
            break
    if workflow_id:
        try:
            await cancel_workflow(workflow_id)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"Temporal cancellation failed: {str(exc)[:500]}") from exc
    job.status = "CANCELLED"
    job.progress = 100
    job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "warning", "message": f"Cancelled by {user.email}"}]
    audit(db, user, "job.cancelled", "job", job.id)
    db.commit()
    return {"id": job.id, "status": job.status, "workflow_id": workflow_id}

@router.post("/jobs/{job_id}/retry", status_code=201)
async def retry_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    original = db.get(Job, job_id)
    require_project_resource(original, project, "Job")
    if original.status not in {"FAILED", "CANCELLED", "PARTIALLY_SUCCEEDED"}:
        raise HTTPException(status_code=409, detail="Only failed, cancelled, or partial jobs can be retried")
    retry = Job(project_id=project.id, title=f"Retry: {original.title}"[:200], job_type=original.job_type, status="RETRYING", progress=5, plan=[{**step, "status": "waiting"} for step in original.plan], evidence=[*original.evidence, {"type": "retry", "label": f"Retry of {original.id[:8]}"}], logs=[{"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Retry requested by {user.email}"}], outputs=[], created_by=user.id)
    db.add(retry)
    db.flush()
    incident = db.scalar(select(Incident).where(Incident.project_id == project.id, Incident.job_id == original.id).order_by(Incident.created_at.desc()).limit(1))
    if incident:
        incident.retry_job_id = retry.id
    audit(db, user, "job.retry_requested", "job", retry.id, {"original_job_id": original.id})
    db.commit()
    try:
        workflow_id = await start_agent_workflow(retry.id, original.title)
    except Exception as exc:
        retry.status = "FAILED"
        retry.progress = 100
        retry.logs = [*retry.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "error", "message": str(exc)[:2000]}]
        db.commit()
        return {"id": retry.id, "status": retry.status, "workflow_id": None}
    if workflow_id:
        retry.status = "QUEUED"
        retry.logs = [*retry.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Temporal workflow {workflow_id} started"}]
    else:
        run_agent_plan_locally(retry.id, original.title)
        db.refresh(retry)
        retry.logs = [*retry.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Executed bounded local retry fallback"}]
    db.commit()
    return {"id": retry.id, "status": retry.status, "workflow_id": workflow_id}

@router.post("/jobs/{job_id}/diagnose", status_code=201)
def diagnose_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    job = db.get(Job, job_id)
    require_project_resource(job, project, "Job")
    error_entries = [entry for entry in job.logs if str(entry.get("level", "")).lower() == "error"]
    root_cause = str(error_entries[-1].get("message")) if error_entries else f"The job ended in {job.status} without a recorded error event."
    remediation = ["Review the failed step and its input contract", "Correct configuration or source availability", "Use governed retry after validation"]
    provider = selected_model_provider(db, user)
    if provider and provider.provider_type != "local_mock":
        try:
            generated = generate_text(provider, "Diagnose a data job from its durable trace. Return JSON only with root_cause string and remediation array of strings. Do not invent evidence.", json.dumps({"title": job.title, "status": job.status, "plan": job.plan, "evidence": job.evidence, "logs": job.logs}, default=str), 1200, governance_feature="job_diagnosis", governance_business_id=project.id, governance_session_id=job.id, governance_user_id=user.id)
            parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", generated.content.strip(), flags=re.I))
            if isinstance(parsed.get("root_cause"), str) and isinstance(parsed.get("remediation"), list):
                root_cause = parsed["root_cause"][:10_000]
                remediation = [str(item)[:1000] for item in parsed["remediation"][:10]]
            db.add(ModelCallLog(project_id=project.id, provider_id=provider.id, model=provider.default_model, purpose="job_diagnosis", status="healthy", latency_ms=generated.latency_ms, created_by=user.id))
        except Exception as exc:
            db.add(ModelCallLog(project_id=project.id, provider_id=provider.id, model=provider.default_model, purpose="job_diagnosis", status="failed", error=str(exc)[:1000], created_by=user.id))
    incident = Incident(project_id=project.id, job_id=job.id, title=f"Incident: {job.title}"[:220], severity="high" if job.status == "FAILED" else "medium", root_cause=root_cause, evidence=[{"type": "job_status", "value": job.status}, *error_entries[-5:]], remediation=remediation, created_by=user.id)
    db.add(incident)
    audit(db, user, "incident.opened", "incident", incident.id, {"job_id": job.id})
    db.commit()
    return as_dict(incident, ["id", "project_id", "job_id", "title", "severity", "status", "root_cause", "evidence", "remediation", "retry_job_id", "created_by", "created_at", "resolved_at"])

@router.get("/incidents")
def list_incidents(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    incidents = db.scalars(select(Incident).where(Incident.project_id == project.id).order_by(Incident.created_at.desc())).all()
    return [as_dict(item, ["id", "project_id", "job_id", "title", "severity", "status", "root_cause", "evidence", "remediation", "retry_job_id", "created_by", "created_at", "resolved_at"]) for item in incidents]

@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str, payload: IncidentResolveRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    incident = db.get(Incident, incident_id)
    if incident is None or incident.project_id != project.id:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident.status = "resolved"
    incident.resolved_at = datetime.now(timezone.utc)
    if payload.note:
        incident.remediation = [*incident.remediation, f"Resolution: {payload.note}"]
    audit(db, user, "incident.resolved", "incident", incident.id)
    db.commit()
    return as_dict(incident, ["id", "status", "resolved_at", "remediation"])

@router.get("/jobs/{job_id}/events")
async def stream_job_events(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StreamingResponse:
    project = require_current_project(db, user)
    require_project_resource(db.get(Job, job_id), project, "Job")
    project_id = project.id

    async def events():
        previous = ""
        for _ in range(600):
            with SessionLocal() as event_db:
                job = event_db.get(Job, job_id)
                if job is None or job.project_id != project_id:
                    yield 'event: error\ndata: {"detail":"Job unavailable"}\n\n'
                    return
                payload = json.dumps(as_dict(job, ["id", "status", "progress", "plan", "evidence", "logs", "updated_at"]), default=str)
                if payload != previous:
                    yield f"event: job\ndata: {payload}\n\n"
                    previous = payload
                if job.status in {"SUCCEEDED", "FAILED", "CANCELLED", "PARTIALLY_SUCCEEDED"}:
                    return
            await asyncio.sleep(1)
        yield 'event: timeout\ndata: {"detail":"Stream duration reached"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
