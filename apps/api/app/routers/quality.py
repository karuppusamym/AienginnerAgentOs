"""Auto-extracted quality routes from the former monolithic main.py.

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


@router.get("/quality/rules")
def list_quality_rules(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    rules = db.scalars(select(QualityRule).where(QualityRule.project_id == project.id).order_by(QualityRule.created_at.desc())).all()
    return [quality_rule_output(rule, db) for rule in rules]

@router.post("/quality/rules", status_code=201)
def create_quality_rule(
    payload: QualityRuleCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    asset = require_project_resource(db.get(DataAsset, payload.asset_id), project, "Dataset")
    columns = {str(column.get("name")) for column in asset.columns}
    if payload.column_name not in columns:
        raise HTTPException(status_code=400, detail="Quality rule column does not exist in the dataset")
    rule = create_quality_rule_record(
        db,
        user,
        asset,
        payload.name,
        payload.rule_type,
        payload.column_name,
        payload.config,
        payload.severity,
    )
    audit(db, user, "quality.rule_created", "quality_rule", rule.id, {"asset_id": asset.id})
    db.commit()
    return quality_rule_output(rule, db)

@router.post("/quality/assets/{asset_id}/suggest", status_code=201)
def suggest_quality_rules(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    asset = require_project_resource(db.get(DataAsset, asset_id), project, "Dataset")
    existing = {
        (rule.rule_type, rule.column_name)
        for rule in db.scalars(select(QualityRule).where(QualityRule.asset_id == asset.id)).all()
    }
    suggestions: list[tuple[str, str, str, dict[str, Any], str]] = []
    for column in asset.columns[:20]:
        column_name = str(column.get("name", ""))
        if column_name and not column.get("nullable", True):
            suggestions.append(
                (f"{column_name} is not null", "not_null", column_name, {}, "error")
            )
    identifier = next(
        (str(column.get("name")) for column in asset.columns if str(column.get("name", "")).endswith("_id")),
        None,
    )
    if identifier:
        suggestions.append((f"{identifier} is unique", "unique", identifier, {}, "error"))
    status_column = next(
        (str(column.get("name")) for column in asset.columns if str(column.get("name", "")).lower() == "status"),
        None,
    )
    if status_column:
        relation = f"{safe_identifier(asset.schema_name, 'main')}.{safe_identifier(asset.table_name, 'dataset')}"
        try:
            values_result = execute_read_only(
                engine,
                f"SELECT DISTINCT {safe_identifier(status_column, 'status')} AS value FROM {relation} WHERE {safe_identifier(status_column, 'status')} IS NOT NULL LIMIT 20",
                20,
            )
            values = [row["value"] for row in values_result["rows"]]
            if values:
                suggestions.append((f"{status_column} uses approved values", "accepted_values", status_column, {"values": values}, "warning"))
        except Exception:
            pass
    created = []
    for name, rule_type, column_name, config, severity in suggestions:
        if (rule_type, column_name) in existing:
            continue
        rule = create_quality_rule_record(db, user, asset, name, rule_type, column_name, config, severity)
        created.append(rule)
        existing.add((rule_type, column_name))
    audit(db, user, "quality.rules_suggested", "data_asset", asset.id, {"created": len(created)})
    db.commit()
    return [quality_rule_output(rule, db) for rule in created]

@router.get("/quality/runs")
def list_quality_runs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    runs = db.scalars(select(QualityRun).where(QualityRun.project_id == project.id).order_by(QualityRun.created_at.desc()).limit(100)).all()
    output = []
    for run in runs:
        rule = db.get(QualityRule, run.rule_id)
        asset = db.get(DataAsset, rule.asset_id) if rule else None
        output.append(
            {
                **as_dict(run, ["id", "rule_id", "status", "checked_rows", "failed_rows", "pass_rate", "sample_failures", "quarantine_relation", "error", "created_at"]),
                "rule_name": rule.name if rule else "Deleted rule",
                "dataset": f"{asset.schema_name}.{asset.table_name}" if asset else "missing asset",
            }
        )
    return output

@router.post("/quality/rules/{rule_id}/run", status_code=201)
def run_quality_rule(
    rule_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    rule = require_project_resource(db.get(QualityRule, rule_id), project, "Quality rule")
    asset = db.get(DataAsset, rule.asset_id)
    if asset is None:
        raise HTTPException(status_code=409, detail="The quality rule dataset no longer exists")
    run = QualityRun(
        id=str(uuid4()),
        project_id=project.id,
        rule_id=rule.id,
        status="running",
        created_by=user.id,
    )
    db.add(run)
    db.flush()
    run_id = run.id
    execution_context = {
        "schema_name": asset.schema_name,
        "table_name": asset.table_name,
        "rule_name": rule.name,
        "rule_type": rule.rule_type,
        "column_name": rule.column_name,
        "config": rule.config,
    }
    db.commit()
    try:
        result = execute_quality_rule(
            engine,
            execution_context["schema_name"],
            execution_context["table_name"],
            execution_context["rule_name"],
            execution_context["rule_type"],
            execution_context["column_name"],
            execution_context["config"],
            run_id,
        )
        for key, value in result.items():
            setattr(run, key, value)
    except Exception as exc:
        run.status = "error"
        run.error = str(exc)[:2000]
    audit(
        db,
        user,
        "quality.rule_executed",
        "quality_run",
        run.id,
        {"rule_id": rule.id, "status": run.status, "failed_rows": run.failed_rows},
    )
    db.commit()
    return {
        **as_dict(run, ["id", "rule_id", "status", "checked_rows", "failed_rows", "pass_rate", "sample_failures", "quarantine_relation", "error", "created_at"]),
        "rule_name": rule.name,
        "dataset": f"{asset.schema_name}.{asset.table_name}",
    }

@router.post("/quality/runs/{run_id}/remediate", status_code=201)
def request_quality_remediation(run_id: str, payload: QualityRemediationRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    project = require_current_project(db, user)
    run = require_project_resource(db.get(QualityRun, run_id), project, "Quality run")
    if payload.action == "purge_quarantine" and not run.quarantine_relation:
        raise HTTPException(status_code=409, detail="This quality run has no quarantine relation")
    job = Job(project_id=project.id, title=f"Quality remediation: {payload.action}", job_type="quality_remediation", status="WAITING_FOR_APPROVAL", progress=60, plan=[{"agent": "Quality", "action": "Validate remediation target", "status": "complete"}, {"agent": "Policy", "action": "Approve quality remediation", "status": "waiting"}], evidence=[{"type": "quality_run", "label": run.id}, {"type": "action", "label": payload.action}], created_by=user.id)
    db.add(job)
    db.flush()
    approval = Approval(project_id=project.id, job_id=job.id, title=f"Approve quality remediation: {payload.action}", action_type="quality_remediation", risk_level="high" if payload.action == "purge_quarantine" else "medium", evidence={"quality_run_id": run.id, "action": payload.action, "note": payload.note, "summary": f"{payload.action} for quality run {run.id}", "checks": ["project ownership", "generated quarantine relation", "audited approval"]}, requested_by=user.id)
    db.add(approval)
    audit(db, user, "quality.remediation_requested", "quality_run", run.id, {"action": payload.action, "approval_id": approval.id})
    db.commit()
    return {"job_id": job.id, "approval_id": approval.id, "status": job.status}
