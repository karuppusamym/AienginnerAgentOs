"""Auto-extracted conversations routes from the former monolithic main.py.

Generated as part of the DataPilot backend restructuring effort
(docs/IMPLEMENTATION_STATUS_MATRIX.md, section 3). Behavior is unchanged;
route handlers were relocated verbatim from apps/api/app/main.py and now
live on a domain-scoped APIRouter instead of the global FastAPI app.
"""
from __future__ import annotations

from .sql import generate_sql
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
from fastapi import APIRouter, Response
import contextvars
import queue
import threading
from collections.abc import Callable, Iterator

from ..models import RouteDecision

from ..decision_router import decide, follow_up_questions

from .. import core as main
from ..core import (
    AGENT_APPROVAL_KEYWORDS, AgentDefinition, AgentDefinitionCreate,
    AgentDefinitionUpdate, AgentRunRequest, AgentVersion, AgentVersionCreate, Any,
    Approval, ApprovalDecision, Artifact, ArtifactComment, ArtifactCommentCreate,
    ArtifactCreate, ArtifactReviewRequest, ArtifactVersion, AuditEvent, AuthProvider,
    AuthProviderUpdate, Base, BaseModel, CORSMiddleware, ConfigDict, Connector,
    ConnectorCreate, ConnectorRuntimeError, ConnectorUpdate, Conversation,
    ConversationAsk, ConversationCreate, ConversationMessage, ConversationRename,
    ConversationReportCreate, DEFAULT_ARTIFACT_TARGETS, DataAsset, Depends,
    EvaluationBaselineRequest, EvaluationCaseInput, EvaluationRun,
    EvaluationRunRequest, EvaluationSet, EvaluationSetCreate, ExternalClient,
    ExternalClientCreate, ExternalClientUpdate, ExternalExtraction,
    ExternalExtractionCreate, ExternalInvocation, FastAPI, FeedbackCreate, Field, File,
    FileStageRequest, Form, HTTPException, Header, Incident, IncidentResolveRequest,
    IngestedFile, IngestionMapping, IngestionSchedule, Job, LearningSuggestion,
    LearningSuggestionReview, LineageEdge, Literal, LoginRequest, MCPRequest,
    MappingColumn, ModelCallLog, ModelProvider, NotebookCell, NotebookSave, ORMModel,
    PasswordChange, Path, PipelineDefinition, PipelineGenerateRequest,
    PipelineGenerationError, PipelinePackageDeliveryConfigSave, PipelinePackageSummary,
    PipelineUpdateRequest, PipelineVersion, Project, ProjectCreate,
    ProjectMemberUpdate, ProjectMembership, ProjectModelUpdate, PromptRollback,
    PromptSave, ProviderCreate, ProviderUpdate, QualityRemediationRequest, QualityRule,
    QualityRuleCreate, QualityRun, Query, QueryTool, QueryToolCreate, QueryToolGrant,
    QueryToolGrantCreate, QueryToolInvoke, QueryToolWizardPreview, RedTeamSuiteCreate,
    Request, RetentionPolicy, RetentionPolicySave, SECURITY_CATEGORIES,
    SECURITY_CATEGORY_LABELS, SECURITY_SEVERITIES, SQLExecutionRequest, SQLQueryCache,
    SQLRequest, ScheduleCreate, SchemaDriftEvent, SchemaMappingCreate,
    SemanticJoinPolicy, SemanticJoinPolicyCreate, SemanticMetric, SemanticMetricCreate,
    Session, SessionLocal, StreamingResponse, SupersetProjectDashboard, ToolDefinition,
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


@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    conversations = db.scalars(select(Conversation).where(Conversation.project_id == project.id).order_by(Conversation.updated_at.desc())).all()
    # One grouped count instead of loading every message of every conversation.
    counts = dict(
        db.execute(
            select(ConversationMessage.conversation_id, func.count())
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .where(Conversation.project_id == project.id)
            .group_by(ConversationMessage.conversation_id)
        ).all()
    )
    latest = (
        select(ConversationMessage.conversation_id, func.max(ConversationMessage.created_at).label("latest_at"))
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .where(Conversation.project_id == project.id)
        .group_by(ConversationMessage.conversation_id)
        .subquery()
    )
    last_messages = {
        conversation_id: content
        for conversation_id, content in db.execute(
            select(ConversationMessage.conversation_id, ConversationMessage.content).join(
                latest,
                (latest.c.conversation_id == ConversationMessage.conversation_id)
                & (latest.c.latest_at == ConversationMessage.created_at),
            )
        ).all()
    }
    return [
        {
            **as_dict(item, ["id", "project_id", "title", "summary", "created_by", "created_at", "updated_at"]),
            "message_count": counts.get(item.id, 0),
            "last_message": (last_messages.get(item.id) or "")[:240] or None,
        }
        for item in conversations
    ]

@router.post("/conversations", status_code=201)
def create_conversation(payload: ConversationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    conversation = Conversation(project_id=project.id, title=payload.title, created_by=user.id)
    db.add(conversation)
    db.flush()
    audit(db, user, "conversation.created", "conversation", conversation.id)
    db.commit()
    return conversation_output(conversation, db)

@router.get("/conversations/{conversation_id}/messages")
def list_conversation_messages(
    conversation_id: str,
    response: Response,
    limit: int = Query(default=200, ge=1, le=500),
    before: str | None = Query(default=None, max_length=36),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Most recent ``limit`` messages (ascending), optionally older than message ``before``."""
    project = require_current_project(db, user)
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.project_id != project.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    query = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id)
    if before:
        anchor = db.get(ConversationMessage, before)
        if anchor is None or anchor.conversation_id != conversation.id:
            raise HTTPException(status_code=404, detail="Anchor message not found")
        query = query.where(ConversationMessage.created_at < anchor.created_at)
    page = db.scalars(query.order_by(ConversationMessage.created_at.desc()).limit(limit + 1)).all()
    response.headers["X-Has-More"] = "true" if len(page) > limit else "false"
    messages = list(reversed(page[:limit]))
    return [as_dict(item, ["id", "conversation_id", "role", "content", "structured", "created_by", "created_at"]) for item in messages]


def _load_conversation(db: Session, user: User, conversation_id: str) -> tuple[Project, Conversation]:
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.project_id != project.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return project, conversation


def _answer_question(
    db: Session,
    user: User,
    project: Project,
    conversation: Conversation,
    payload: ConversationAsk,
    progress: Callable[[str, str], None] = lambda _stage, _label: None,
    cancelled: threading.Event | None = None,
) -> dict[str, Any]:
    """One chat turn: ground + generate SQL, execute, route, answer, persist.

    Shared by the JSON and streaming endpoints. The user turn is written only
    after generation succeeds: flushing it first held SQLite's write lock
    across every model call, and a failed generation (which commits its own
    call log) left an unanswered message that polluted the next question.
    """
    prior_messages = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at)
    ).all()
    progress("grounding", "Finding relevant tables, metrics and joins, then drafting governed SQL")
    analysis = generate_sql(
        SQLRequest(
            question=payload.content,
            dialect=payload.dialect,
            connector_id=payload.connector_id,
            conversation_context=compact_conversation_context(prior_messages, conversation.summary),
        ),
        user,
        db,
    )
    execution = analysis.get("execution")
    if execution is None and payload.connector_id and _safe_read_only_sql(analysis.get("sql", ""), analysis.get("dialect")):
        progress("executing", "Running a bounded read-only preview on the source system")
        connector = require_project_resource(db.get(Connector, payload.connector_id), project, "Connector")
        try:
            execution = main.execute_connector_query(
                connector,
                analysis["sql"],
                {},
                500,
                30,
                user_id=user.id,
                session_id=conversation.id,
                feature="conversation_analysis",
            )
        except Exception as exc:
            execution = {
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "limit": 500,
                "duration_ms": 0,
                "error": str(exc),
            }
        analysis["execution"] = execution
        analysis["preview"] = execution.get("rows", [])
        checks = analysis.get("validation", {}).get("checks")
        if isinstance(checks, list):
            status_line = (
                "Executed against configured source system"
                if not execution.get("error")
                else "Execution failed against configured source system"
            )
            analysis["validation"]["checks"] = [
                status_line if check == "Execution requires the matching configured source system" else check
                for check in checks
            ]
    progress("routing", "Scoring SQL, governed tools and agents for this request")
    try:
        routing_model = selected_model_provider(db, user, "decision_routing")
    except HTTPException:
        routing_model = None
    route = decide(db, project.id, payload.content, analysis.get("grounding"), llm_provider=routing_model)
    progress("answering", "Writing the answer")
    try:
        provider = selected_model_provider(db, user, "conversation_summary")
    except HTTPException:
        provider = selected_model_provider(db, user)
    chart = _chart_from_result(payload.content, execution)
    row_count = execution.get("row_count", 0) if execution else 0
    answer = conversational_analysis_answer(
        provider,
        payload.content,
        analysis,
        len(prior_messages),
        project_id=project.id,
        session_id=conversation.id,
        user_id=user.id,
    ) if provider else "I prepared a governed analysis."
    if route["route"] == "clarify" and not row_count:
        answer = (
            "I could not ground this question confidently in the catalog, so treat the draft query below as a guess. "
            "Which table, metric or time range do you mean? " + answer
        )
    if cancelled is not None and cancelled.is_set():
        db.rollback()
        raise HTTPException(status_code=499, detail="Request cancelled by the client before the answer was saved")
    user_message = ConversationMessage(conversation_id=conversation.id, role="user", content=payload.content, created_by=user.id)
    db.add(user_message)
    db.flush()
    structured = {
        "question": payload.content,
        "sql": analysis["sql"],
        "dialect": analysis["dialect"],
        "provider": analysis["provider"],
        "cache": analysis.get("cache"),
        "grounding": analysis.get("grounding"),
        "validation": analysis["validation"],
        "sources": analysis["sources"],
        "execution": json.loads(json.dumps(execution, default=str)) if execution else None,
        "chart": chart,
        "source": analysis["source"],
        "memory": {"prior_messages_used": len(prior_messages), "persisted": True},
        "route": route,
        "follow_ups": follow_up_questions(payload.content, execution),
    }
    assistant_message = ConversationMessage(conversation_id=conversation.id, role="assistant", content=answer, structured=structured)
    db.add(assistant_message)
    db.flush()
    db.add(RouteDecision(
        project_id=project.id,
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        question=payload.content[:4_000],
        route=route["route"],
        confidence=route["confidence"],
        backend=route["backend"],
        policy_version=route["policy_version"],
        candidates=route["candidates"],
        risk=route["risk"],
        outcome={"execution_error": bool((execution or {}).get("error")), "row_count": row_count},
        created_by=user.id,
    ))
    conversation.summary = refresh_conversation_summary(conversation, [*prior_messages, user_message, assistant_message])
    structured["memory"]["summary"] = conversation.summary or None
    if conversation.title == "New analysis":
        conversation.title = payload.content[:200]
    conversation.updated_at = datetime.now(timezone.utc)
    audit(db, user, "conversation.answered", "conversation", conversation.id, {
        "dialect": payload.dialect,
        "row_count": row_count,
        "route": route["route"],
        "route_confidence": route["confidence"],
        "route_backend": route["backend"],
        "route_policy": route["policy_version"],
    })
    db.commit()
    return as_dict(assistant_message, ["id", "conversation_id", "role", "content", "structured", "created_by", "created_at"])


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def ask_conversation(conversation_id: str, payload: ConversationAsk, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project, conversation = _load_conversation(db, user, conversation_id)
    return _answer_question(db, user, project, conversation, payload)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/conversations/{conversation_id}/messages/stream")
def ask_conversation_stream(conversation_id: str, payload: ConversationAsk, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StreamingResponse:
    """Server-sent events: ``stage`` progress, then ``done`` with the saved message or ``error``.

    The work runs on its own session in a worker thread, so the request holds no
    database connection or transaction while models are called. If the client
    disconnects, the answer is discarded instead of being saved.
    """
    project, conversation = _load_conversation(db, user, conversation_id)
    user_id, project_id, conv_id = user.id, project.id, conversation.id
    db.close()
    events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
    cancelled = threading.Event()

    def work() -> None:
        with SessionLocal() as session:
            try:
                worker_user = session.get(User, user_id)
                message = _answer_question(
                    session,
                    worker_user,
                    session.get(Project, project_id),
                    session.get(Conversation, conv_id),
                    payload,
                    progress=lambda stage, label: events.put(("stage", {"stage": stage, "label": label})),
                    cancelled=cancelled,
                )
                events.put(("done", {"message": message}))
            except HTTPException as exc:
                events.put(("error", {"detail": exc.detail, "status": exc.status_code}))
            except Exception as exc:  # pragma: no cover - surfaced to the client
                events.put(("error", {"detail": str(exc)[:500], "status": 500}))
            finally:
                events.put(None)

    # copy_context keeps the request id and pinned project for the worker thread.
    threading.Thread(target=contextvars.copy_context().run, args=(work,), name="conversation-answer", daemon=True).start()

    def stream() -> Iterator[str]:
        try:
            while True:
                try:
                    item = events.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    return
                yield _sse(*item)
        finally:
            cancelled.set()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

@router.post("/conversations/{conversation_id}/report", status_code=201)
def save_conversation_report(conversation_id: str, payload: ConversationReportCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.project_id != project.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.created_at)).all()
    content = json.dumps({"conversation_id": conversation.id, "title": conversation.title, "messages": [{"role": item.role, "content": item.content, "structured": item.structured} for item in messages]}, indent=2, default=str)
    artifact, version = save_internal_artifact_version(db, user, payload.name, "report", content, {"conversation_id": conversation.id, "message_count": len(messages), "state": "saved"})
    audit(db, user, "conversation.report_saved", "artifact", artifact.id, {"conversation_id": conversation.id})
    db.commit()
    return {"id": artifact.id, "name": artifact.name, "artifact_type": artifact.artifact_type, "version": version.version}

@router.put("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, payload: ConversationRename, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.project_id != project.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.created_by != user.id and not main.can_manage_shared_content(user, db):
        raise HTTPException(status_code=403, detail="Only project owners and maintainers can rename other people's conversations")
    conversation.title = payload.title.strip()
    conversation.updated_at = datetime.now(timezone.utc)
    audit(db, user, "conversation.renamed", "conversation", conversation_id, {"title": conversation.title})
    db.commit()
    return {"id": conversation.id, "title": conversation.title}

@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.project_id != project.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.created_by != user.id and not main.can_manage_shared_content(user, db):
        raise HTTPException(status_code=403, detail="Only project owners and maintainers can delete other people's conversations")
    for message in db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id)).all():
        db.delete(message)
    db.delete(conversation)
    audit(db, user, "conversation.deleted", "conversation", conversation_id)
    db.commit()
    return {"id": conversation_id, "status": "deleted"}
