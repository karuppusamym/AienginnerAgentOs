"""Auto-extracted agents routes from the former monolithic main.py.

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


@router.post("/agents/runs", status_code=201)
async def start_agent_run(
    payload: AgentRunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    requires_approval = agent_run_requires_approval(payload.objective)
    status = "WAITING_FOR_APPROVAL" if requires_approval else "PLANNING"
    plan = initial_agent_plan(requires_approval)
    # This evidence is what a human approver sees *before* the real
    # grounding/retrieval pass runs (that only happens post-approval, in
    # temporal_activities.py). It previously showed a hardcoded, never-computed
    # "3 assets considered" string here — a fabricated number that looked like
    # a real retrieval result to whoever was deciding the approval. Report an
    # honest, cheap-to-compute count of the project's catalog instead of a
    # number nothing ever calculated.
    catalog_size = db.scalar(select(func.count()).select_from(DataAsset).where(DataAsset.project_id == project.id)) or 0
    job = Job(
        project_id=project.id,
        title=payload.objective[:200],
        job_type="agent_run",
        status=status,
        progress=10 if requires_approval else 5,
        plan=plan,
        evidence=[
            {"type": "catalog", "label": f"{catalog_size} assets in project catalog (grounding runs after approval)"},
            {"type": "policy", "label": f"Autonomy level {payload.autonomy_level}"},
            {"type": "limit", "label": "5 agents / 12 tool calls / 5 minute budget"},
        ],
        outputs=[],
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    approval_id = None
    if requires_approval:
        approval = Approval(
            project_id=project.id,
            job_id=job.id,
            title=f"Approve controlled action: {payload.objective[:120]}",
            action_type="agent_execution",
            risk_level="medium",
            requested_by=user.id,
            evidence={
                "objective": payload.objective,
                "guardrails": ["local execution only", "no destructive SQL", "full audit trace"],
            },
        )
        db.add(approval)
        db.flush()
        approval_id = approval.id
    audit(db, user, "agent.run_started", "job", job.id, {"autonomy_level": payload.autonomy_level})
    db.commit()
    workflow_id = None
    if not requires_approval:
        try:
            workflow_id = await start_agent_workflow(job.id, payload.objective)
        except Exception as exc:
            job.status = "FAILED"
            job.progress = 100
            job.logs = [{"at": datetime.now(timezone.utc).isoformat(), "level": "error", "message": f"Temporal workflow start failed: {str(exc)[:500]}"}]
        if workflow_id:
            job.status = "QUEUED"
            job.logs = [{"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Temporal workflow {workflow_id} started"}]
        elif job.status != "FAILED":
            run_agent_plan_locally(job.id, payload.objective)
            db.refresh(job)
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Executed bounded local agent fallback"}]
        db.commit()
        status = job.status
        plan = job.plan
    return {"job_id": job.id, "status": status, "plan": plan, "approval_id": approval_id, "workflow_id": workflow_id}

def _validate_query_tool_names(db: Session, project: Project, query_tool_names: list[str]) -> None:
    """Bound agents may only reference published SQL query tools in the current
    project's registry -- the same governed, business-described QueryTool
    records exposed to external accessors via /query-tools and /external/v1.
    Unlike ToolDefinition (a global registry), QueryTool is project-scoped, so
    this check -- and the runtime lookup in temporal_activities.py -- resolves
    names against whichever project the agent is bound (or run) in."""
    if not query_tool_names:
        return
    known = set(
        db.scalars(
            select(QueryTool.name).where(
                QueryTool.project_id == project.id,
                QueryTool.name.in_(query_tool_names),
                QueryTool.status == "published",
            )
        ).all()
    )
    missing = set(query_tool_names) - known
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Every selected query tool must exist and be published in this project: {', '.join(sorted(missing))}",
        )


@router.get("/agents")
def list_agents(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    agents = db.scalars(select(AgentDefinition).order_by(AgentDefinition.name)).all()
    output = []
    for agent in agents:
        latest = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).limit(1))
        output.append({**as_dict(agent, ["id", "name", "purpose", "autonomy_level", "enabled", "tool_names", "query_tool_names", "policy"]), "current_version": latest.version if latest else 0, "version_status": latest.status if latest else "unversioned", "model_provider_id": latest.model_provider_id if latest else None, "evaluation_score": latest.evaluation_score if latest else None})
    return output

@router.post("/agents", status_code=201)
def create_agent(payload: AgentDefinitionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    project = require_current_project(db, user)
    if db.scalar(select(AgentDefinition).where(func.lower(AgentDefinition.name) == payload.name.lower())):
        raise HTTPException(status_code=409, detail="An agent with this name already exists")
    known_tools = set(db.scalars(select(ToolDefinition.name).where(ToolDefinition.name.in_(payload.tool_names))).all()) if payload.tool_names else set()
    if known_tools != set(payload.tool_names):
        raise HTTPException(status_code=400, detail="Every selected tool must exist in the registry")
    _validate_query_tool_names(db, project, payload.query_tool_names)
    agent = AgentDefinition(name=payload.name, purpose=payload.purpose, autonomy_level=payload.autonomy_level, enabled=payload.enabled, tool_names=payload.tool_names, query_tool_names=payload.query_tool_names, policy=payload.policy)
    db.add(agent)
    db.flush()
    version = AgentVersion(agent_id=agent.id, version=1, instructions=payload.instructions, model_provider_id=payload.model_provider_id, tool_names=payload.tool_names, query_tool_names=payload.query_tool_names, input_schema=payload.input_schema, config=payload.config, status="draft", created_by=user.id)
    db.add(version)
    audit(db, user, "agent.created", "agent", agent.id, {"version": 1})
    db.commit()
    return {**as_dict(agent, ["id", "name", "purpose", "autonomy_level", "enabled", "tool_names", "query_tool_names", "policy"]), "current_version": 1, "version_status": "draft"}

@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    project = require_current_project(db, user)
    versions = db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc())).all()
    current_tools = versions[0].tool_names if versions else agent.tool_names
    current_query_tools = (versions[0].query_tool_names if versions else agent.query_tool_names) or []
    tools = db.scalars(select(ToolDefinition).where(ToolDefinition.name.in_(current_tools))).all() if current_tools else []
    query_tools = (
        db.scalars(
            select(QueryTool).where(QueryTool.project_id == project.id, QueryTool.name.in_(current_query_tools))
        ).all()
        if current_query_tools
        else []
    )
    return {
        **as_dict(agent, ["id", "name", "purpose", "autonomy_level", "enabled", "tool_names", "query_tool_names", "policy"]),
        "tools": [as_dict(tool, ["id", "name", "category", "description", "risk_level", "enabled", "requires_approval"]) for tool in tools],
        "query_tools": [as_dict(tool, ["id", "name", "description", "purpose", "data_source", "line_of_business", "owner", "status", "requires_approval"]) for tool in query_tools],
        "versions": [as_dict(version, ["id", "version", "instructions", "model_provider_id", "tool_names", "query_tool_names", "input_schema", "config", "status", "evaluation_score", "created_by", "created_at"]) for version in versions],
    }

@router.get("/agents/{agent_id}/scorecard")
def get_agent_scorecard(
    agent_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    runs = db.scalars(
        select(EvaluationRun)
        .join(EvaluationSet, EvaluationRun.evaluation_set_id == EvaluationSet.id)
        .where(EvaluationSet.project_id == project.id)
        .order_by(EvaluationRun.created_at.desc())
        .limit(100)
    ).all()
    cases = []
    for run in runs:
        for result in run.results:
            agent_checks = [
                check for check in result.get("checks", [])
                if check.get("kind") == "agent" and check.get("value") == agent.name
            ]
            if not agent_checks:
                continue
            passed = all(bool(check.get("passed")) for check in agent_checks)
            golden_checks = [
                check for check in result.get("checks", [])
                if str(check.get("kind", "")).startswith("golden_")
            ]
            cases.append(
                {
                    "run_id": run.id,
                    "case": result.get("name"),
                    "status": "passed" if passed and all(check.get("passed") for check in golden_checks) else "failed",
                    "score": float(result.get("score", 0.0)),
                    "golden_checks": len(golden_checks),
                    "golden_failures": sum(1 for check in golden_checks if not check.get("passed")),
                    "created_at": run.created_at,
                }
            )
    passed_cases = sum(1 for case in cases if case["status"] == "passed")
    pass_rate = round(100 * passed_cases / len(cases), 2) if cases else None
    average_case_score = round(sum(case["score"] for case in cases) / len(cases), 2) if cases else None
    golden_failures = sum(case["golden_failures"] for case in cases)

    # Close the "self-learning loop" gap noted in docs/IMPLEMENTATION_STATUS_MATRIX.md:
    # AgentVersion.evaluation_score existed on the model but nothing ever wrote to it,
    # and there was no signal connecting evaluation results to publish decisions. This
    # persists the measured score on the latest version and computes a human-reviewable
    # promotion recommendation. It never publishes automatically — publish still requires
    # the existing POST /agents/{agent_id}/versions/{version}/publish action, on purpose:
    # DataPilot's stated governance posture is "learning stays human-reviewed."
    versions = db.scalars(
        select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc())
    ).all()
    latest_version = versions[0] if versions else None
    published_version = next((version for version in versions if version.status == "published"), None)
    if latest_version is not None and average_case_score is not None:
        latest_version.evaluation_score = average_case_score
        db.commit()

    promotion_recommendation: dict[str, Any]
    promotion_threshold = {"min_pass_rate": 80.0, "max_golden_failures": 0}
    if latest_version is None:
        promotion_recommendation = {"status": "no_version", "recommended": False, "reason": "This agent has no versions yet."}
    elif not cases:
        promotion_recommendation = {"status": "not_evaluated", "recommended": False, "reason": "No evaluation cases have exercised this agent yet. Run an evaluation set with an agent check to generate a score."}
    elif latest_version.status == "published":
        promotion_recommendation = {"status": "current", "recommended": False, "reason": f"Version {latest_version.version} is already published."}
    elif pass_rate is not None and pass_rate >= promotion_threshold["min_pass_rate"] and golden_failures <= promotion_threshold["max_golden_failures"]:
        promotion_recommendation = {
            "status": "ready",
            "recommended": True,
            "reason": f"Draft version {latest_version.version} passed {pass_rate}% of {len(cases)} evaluated cases with no golden-check failures.",
        }
    else:
        promotion_recommendation = {
            "status": "below_threshold",
            "recommended": False,
            "reason": f"Draft version {latest_version.version} is at {pass_rate}% pass rate with {golden_failures} golden-check failure(s); the promotion bar is {promotion_threshold['min_pass_rate']}% and zero failures.",
        }
    promotion_recommendation["threshold"] = promotion_threshold
    promotion_recommendation["candidate_version"] = latest_version.version if latest_version else None
    promotion_recommendation["published_version"] = published_version.version if published_version else None

    return {
        "agent_id": agent.id,
        "agent": agent.name,
        "evaluated_cases": len(cases),
        "passed_cases": passed_cases,
        "pass_rate": pass_rate,
        "average_case_score": average_case_score,
        "golden_failures": golden_failures,
        "recent_cases": cases[:20],
        "promotion_recommendation": promotion_recommendation,
    }

@router.put("/agents/{agent_id}")
def update_agent(agent_id: str, payload: AgentDefinitionUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    duplicate = db.scalar(select(AgentDefinition).where(func.lower(AgentDefinition.name) == payload.name.lower(), AgentDefinition.id != agent.id))
    if duplicate:
        raise HTTPException(status_code=409, detail="An agent with this name already exists")
    for field, value in payload.model_dump().items():
        setattr(agent, field, value)
    audit(db, user, "agent.updated", "agent", agent.id)
    db.commit()
    return as_dict(agent, ["id", "name", "purpose", "autonomy_level", "enabled", "tool_names", "policy"])

@router.post("/agents/{agent_id}/versions", status_code=201)
def create_agent_version(agent_id: str, payload: AgentVersionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    project = require_current_project(db, user)
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    known_tools = set(db.scalars(select(ToolDefinition.name).where(ToolDefinition.name.in_(payload.tool_names))).all()) if payload.tool_names else set()
    if known_tools != set(payload.tool_names):
        raise HTTPException(status_code=400, detail="Every selected tool must exist in the registry")
    _validate_query_tool_names(db, project, payload.query_tool_names)
    next_version = (db.scalar(select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent.id)) or 0) + 1
    version = AgentVersion(agent_id=agent.id, version=next_version, status="draft", created_by=user.id, **payload.model_dump())
    db.add(version)
    agent.tool_names = payload.tool_names
    agent.query_tool_names = payload.query_tool_names
    audit(db, user, "agent.version_created", "agent", agent.id, {"version": next_version})
    db.commit()
    return as_dict(version, ["id", "version", "instructions", "model_provider_id", "tool_names", "query_tool_names", "input_schema", "config", "status", "created_at"])

@router.post("/agents/{agent_id}/versions/{version_number}/publish")
def publish_agent_version(agent_id: str, version_number: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"admin", "engineer"}:
        raise HTTPException(status_code=403, detail="Admin or engineer role required")
    version = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version == version_number))
    if version is None:
        raise HTTPException(status_code=404, detail="Agent version not found")
    for candidate in db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id)).all():
        if candidate.status == "published":
            candidate.status = "retired"
    version.status = "published"
    audit(db, user, "agent.version_published", "agent", agent_id, {"version": version_number})
    db.commit()
    return {"agent_id": agent_id, "version": version_number, "status": version.status}
