"""Auto-extracted artifacts routes from the former monolithic main.py.

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


@router.get("/artifacts")
def list_artifacts(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    artifacts = db.scalars(select(Artifact).where(Artifact.project_id == project.id).order_by(Artifact.updated_at.desc())).all()
    output = []
    for artifact in artifacts:
        latest = db.scalar(
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_id == artifact.id)
            .order_by(ArtifactVersion.version.desc())
            .limit(1)
        )
        output.append(
            {
                **as_dict(
                    artifact,
                    ["id", "name", "artifact_type", "status", "created_by", "created_at", "updated_at"],
                ),
                "latest_version": latest.version if latest else 0,
                "metadata": latest.artifact_metadata if latest else {},
            }
        )
    return output

@router.post("/artifacts", status_code=201)
def save_artifact(
    payload: ArtifactCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_workspace_editor(user)
    project = require_current_project(db, user)
    if payload.artifact_id:
        artifact = db.get(Artifact, payload.artifact_id)
        require_project_resource(artifact, project, "Artifact")
        artifact.name = payload.name
        artifact.updated_at = datetime.now(timezone.utc)
    else:
        artifact = Artifact(
            project_id=project.id,
            name=payload.name,
            artifact_type=payload.artifact_type,
            created_by=user.id,
        )
        db.add(artifact)
        db.flush()
    current_version = db.scalar(
        select(func.max(ArtifactVersion.version)).where(ArtifactVersion.artifact_id == artifact.id)
    ) or 0
    version = ArtifactVersion(
        artifact_id=artifact.id,
        version=current_version + 1,
        content=payload.content,
        artifact_metadata=payload.metadata,
        created_by=user.id,
    )
    db.add(version)
    db.flush()
    audit(
        db,
        user,
        "artifact.version_saved",
        "artifact",
        artifact.id,
        {"version": version.version, "artifact_type": artifact.artifact_type},
    )
    db.commit()
    return {
        "id": artifact.id,
        "name": artifact.name,
        "artifact_type": artifact.artifact_type,
        "status": artifact.status,
        "version": version.version,
        "metadata": version.artifact_metadata,
        "created_at": version.created_at,
    }

@router.get("/artifacts/{artifact_id}/versions")
def list_artifact_versions(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    require_project_resource(db.get(Artifact, artifact_id), project, "Artifact")
    versions = db.scalars(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.version.desc())
    ).all()
    return [
        as_dict(version, ["id", "artifact_id", "version", "content", "artifact_metadata", "created_by", "created_at"])
        for version in versions
    ]

@router.get("/artifacts/{artifact_id}/diff")
def diff_artifact_versions(
    artifact_id: str,
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    require_project_resource(db.get(Artifact, artifact_id), project, "Artifact")
    versions = db.scalars(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.version.in_([from_version, to_version]),
        )
    ).all()
    by_number = {version.version: version for version in versions}
    if from_version not in by_number or to_version not in by_number:
        raise HTTPException(status_code=404, detail="An artifact version was not found")
    lines = list(
        unified_diff(
            by_number[from_version].content.splitlines(),
            by_number[to_version].content.splitlines(),
            fromfile=f"v{from_version}",
            tofile=f"v{to_version}",
            lineterm="",
        )
    )
    return {"artifact_id": artifact_id, "from_version": from_version, "to_version": to_version, "diff": "\n".join(lines)}

@router.get("/artifacts/{artifact_id}/comments")
def list_artifact_comments(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    require_project_resource(db.get(Artifact, artifact_id), project, "Artifact")
    comments = db.scalars(
        select(ArtifactComment)
        .where(ArtifactComment.artifact_id == artifact_id)
        .order_by(ArtifactComment.created_at.desc())
    ).all()
    return [
        {
            **as_dict(comment, ["id", "artifact_id", "version", "body", "created_by", "created_at"]),
            "author": (db.get(User, comment.created_by).name if db.get(User, comment.created_by) else "Unknown user"),
        }
        for comment in comments
    ]

@router.post("/artifacts/{artifact_id}/comments", status_code=201)
def add_artifact_comment(
    artifact_id: str,
    payload: ArtifactCommentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_workspace_editor(user)
    project = require_current_project(db, user)
    artifact = require_project_resource(db.get(Artifact, artifact_id), project, "Artifact")
    if payload.version is not None and db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.version == payload.version,
        )
    ) is None:
        raise HTTPException(status_code=404, detail="Artifact version not found")
    comment = ArtifactComment(
        artifact_id=artifact_id,
        version=payload.version,
        body=payload.body,
        created_by=user.id,
    )
    db.add(comment)
    audit(db, user, "artifact.commented", "artifact", artifact.id, {"version": payload.version})
    db.commit()
    return {**as_dict(comment, ["id", "artifact_id", "version", "body", "created_at"]), "author": user.name}

@router.post("/artifacts/{artifact_id}/review")
def review_artifact(
    artifact_id: str,
    payload: ArtifactReviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    artifact = require_project_resource(db.get(Artifact, artifact_id), project, "Artifact")
    if payload.decision == "approved" and user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required for approval")
    artifact.status = payload.decision
    artifact.updated_at = datetime.now(timezone.utc)
    if payload.note:
        db.add(ArtifactComment(artifact_id=artifact.id, body=payload.note, created_by=user.id))
    audit(db, user, f"artifact.{payload.decision}", "artifact", artifact.id)
    db.commit()
    return {"id": artifact.id, "status": artifact.status, "updated_at": artifact.updated_at}
