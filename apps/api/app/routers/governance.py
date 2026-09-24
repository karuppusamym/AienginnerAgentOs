"""Auto-extracted governance routes from the former monolithic main.py.

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

from ..models import RouteDecision

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


@router.get("/policies/effective")
def effective_policy(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    membership = main.current_membership(db, user)
    project = db.get(Project, membership.project_id) if membership else None
    return {
        "project": project.name if project else None,
        "autonomy_levels": [0, 1, 2, 3],
        "default_autonomy_level": 2,
        "max_iterations": 4,
        "max_tool_calls": 12,
        "timeout_seconds": 300,
        "read_only_by_default": True,
        "writes_require_approval": True,
        "external_actions_require_approval": True,
    }

@router.get("/audit")
def get_audit_log(
    admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, admin)
    events = db.scalars(select(AuditEvent).where(AuditEvent.project_id == project.id).order_by(AuditEvent.created_at.desc()).limit(100)).all()
    return [
        as_dict(event, ["id", "actor_id", "event_type", "entity_type", "entity_id", "details", "created_at"])
        for event in events
    ]

@router.post("/feedback", status_code=201)
def create_feedback(
    payload: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    item = UserFeedback(project_id=project.id, created_by=user.id, **payload.model_dump())
    db.add(item)
    db.flush()
    if payload.context_id:
        decision = db.scalar(select(RouteDecision).where(RouteDecision.project_id == project.id, RouteDecision.message_id == payload.context_id))
        if decision is not None:
            decision.outcome = {**(decision.outcome or {}), "feedback": payload.rating, "feedback_comment": (payload.comment or "")[:500] or None}
    suggestion = None
    if payload.rating == "not_helpful":
        category = {
            "sql": "sql_grounding",
            "agent_run": "agent_behavior",
            "dataset": "catalog_metadata",
            "notebook": "notebook_workflow",
            "artifact": "artifact_quality",
        }[payload.context_type]
        # Pattern detection over repeated signal, not per-feedback noise: fold
        # new "not helpful" feedback into an existing open suggestion for the
        # same category within a rolling 30-day window instead of creating a
        # fresh row every time, and escalate severity as occurrences climb.
        # This is DataPilot's actual self-learning loop (see
        # docs/ARCHITECTURE_DECISIONS.md section 2) — it detects trends from
        # feedback automatically, but every change still requires a human
        # decision via PUT /learning-suggestions/{id}; nothing here changes
        # runtime behavior on its own.
        window_start = datetime.now(timezone.utc) - timedelta(days=30)
        existing = db.scalar(
            select(LearningSuggestion)
            .where(
                LearningSuggestion.project_id == project.id,
                LearningSuggestion.category == category,
                LearningSuggestion.status == "open",
                LearningSuggestion.created_at >= window_start,
            )
            .order_by(LearningSuggestion.created_at.desc())
        )
        if existing is not None:
            existing.occurrence_count += 1
            existing.severity = "high" if existing.occurrence_count >= 6 else "elevated" if existing.occurrence_count >= 3 else "normal"
            recent_signals = existing.proposed_change.get("recent_signals", []) if isinstance(existing.proposed_change, dict) else []
            recent_signals = [*recent_signals, {"feedback_id": item.id, "context_id": payload.context_id, "comment": payload.comment}][-10:]
            existing.proposed_change = {**existing.proposed_change, "recent_signals": recent_signals, "occurrence_count": existing.occurrence_count}
            existing.rationale = f"{existing.occurrence_count} not-helpful signals in {category.replace('_', ' ')} over the last 30 days — most recent: {(payload.comment or 'no comment provided')[:500]}"
            suggestion = existing
        else:
            suggestion = LearningSuggestion(
                project_id=project.id,
                feedback_id=item.id,
                category=category,
                title=f"Review {payload.context_type.replace('_', ' ')} feedback",
                rationale=(payload.comment or "A user marked this governed output as not helpful.")[:5_000],
                occurrence_count=1,
                severity="normal",
                proposed_change={
                    "review_target": payload.context_type,
                    "context_id": payload.context_id,
                    "action": "Review evidence and propose a versioned improvement; do not change runtime behavior automatically.",
                    "recent_signals": [{"feedback_id": item.id, "context_id": payload.context_id, "comment": payload.comment}],
                },
            )
            db.add(suggestion)
        db.flush()
    audit(db, user, "feedback.created", payload.context_type, payload.context_id, {"rating": payload.rating})
    if suggestion:
        audit(db, user, "learning_suggestion.created", "learning_suggestion", suggestion.id, {"category": suggestion.category, "feedback_id": item.id})
    db.commit()
    main.record_governance_score(
        score_id=item.id,
        name="user_helpfulness",
        value=payload.rating == "helpful",
        data_type="BOOLEAN",
        session_id=payload.context_id,
        comment="User marked output helpful" if payload.rating == "helpful" else "User marked output not helpful",
    )
    return {
        **as_dict(item, ["id", "context_type", "context_id", "rating", "comment", "created_by", "created_at"]),
        "learning_suggestion_id": suggestion.id if suggestion else None,
    }

@router.get("/feedback")
def list_feedback(
    admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, admin)
    items = db.scalars(select(UserFeedback).where(UserFeedback.project_id == project.id).order_by(UserFeedback.created_at.desc()).limit(200)).all()
    return [as_dict(item, ["id", "context_type", "context_id", "rating", "comment", "created_by", "created_at"]) for item in items]

@router.get("/learning-suggestions")
def list_learning_suggestions(
    status: Literal["open", "accepted", "dismissed"] | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, admin)
    statement = select(LearningSuggestion).where(LearningSuggestion.project_id == project.id)
    if status:
        statement = statement.where(LearningSuggestion.status == status)
    suggestions = db.scalars(statement.order_by(LearningSuggestion.created_at.desc()).limit(200)).all()
    return [
        as_dict(
            suggestion,
            [
                "id", "feedback_id", "category", "status", "title", "rationale",
                "proposed_change", "reviewed_by", "review_note", "occurrence_count", "severity",
                "created_at", "reviewed_at",
            ],
        )
        for suggestion in suggestions
    ]

@router.put("/learning-suggestions/{suggestion_id}")
def review_learning_suggestion(
    suggestion_id: str,
    payload: LearningSuggestionReview,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, admin)
    suggestion = db.get(LearningSuggestion, suggestion_id)
    if suggestion is None or suggestion.project_id != project.id:
        raise HTTPException(status_code=404, detail="Learning suggestion not found")
    if suggestion.status != "open":
        raise HTTPException(status_code=409, detail="Learning suggestion has already been reviewed")
    suggestion.status = payload.status
    suggestion.reviewed_by = admin.id
    suggestion.review_note = payload.note
    suggestion.reviewed_at = datetime.now(timezone.utc)
    audit(db, admin, f"learning_suggestion.{payload.status}", "learning_suggestion", suggestion.id)
    db.commit()
    return as_dict(
        suggestion,
        ["id", "feedback_id", "category", "status", "title", "rationale", "proposed_change", "reviewed_by", "review_note", "occurrence_count", "severity", "created_at", "reviewed_at"],
    )
