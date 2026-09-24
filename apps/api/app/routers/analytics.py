"""Auto-extracted analytics routes from the former monolithic main.py.

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
    SupersetQueryDashboard,
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

from ..superset_client import superset_availability
from ..charts import infer_column_types

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
    SupersetPublishRequest, ScheduleCreate, SchemaDriftEvent, SchemaMappingCreate,
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


@router.get("/analytics/config")
def analytics_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    try:
        dataset = resolve_superset_dataset(db, project)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        config = main.get_embed_configuration(project.name, project.slug, dataset)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=503, detail=f"Embedded analytics is unavailable: {exc}") from exc
    state = save_superset_dashboard_state(db, project, dataset, config)
    db.commit()
    return {
        **config,
        "mapped_at": state.updated_at.isoformat() if state.updated_at else None,
        "dataset_column_count": state.dataset_column_count,
    }

@router.post("/analytics/guest-token")
def analytics_guest_token(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    project = require_current_project(db, user)
    try:
        dataset = resolve_superset_dataset(db, project)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        return create_guest_token(
            project.name,
            project.slug,
            dataset,
            user.id,
            user.email,
            user.name,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=503, detail=f"Embedded analytics is unavailable: {exc}") from exc

@router.post("/analytics/editor-session")
def analytics_editor_session(admin: User = Depends(require_admin)) -> dict[str, Any]:
    try:
        return create_editor_url(admin.id, admin.email, admin.name, admin.role)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/publish-sql", status_code=202)
def request_sql_publication(
    payload: SupersetPublishRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Request publication of a saved SQL/notebook query as Superset data.

    The query is never accepted from the browser.  It must come from an
    immutable DataPilot artifact version, be locally executable, and is copied
    into approval evidence before an approver can promote it.
    """
    require_workspace_editor(user, db)
    project = require_current_project(db, user)
    if bool(payload.artifact_id) == bool(payload.notebook_id):
        raise HTTPException(status_code=422, detail="Select exactly one saved SQL artifact or notebook")

    source_id = payload.artifact_id or payload.notebook_id
    artifact = require_project_resource(db.get(Artifact, source_id), project, "Artifact")
    latest = db.scalar(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version.desc())
        .limit(1)
    )
    if latest is None:
        raise HTTPException(status_code=409, detail="The selected artifact has no saved version")

    if payload.artifact_id:
        if artifact.artifact_type != "sql":
            raise HTTPException(status_code=422, detail="Only SQL artifacts can be published to Superset")
        metadata = latest.artifact_metadata or {}
        if metadata.get("connector_id") or metadata.get("dialect", "postgres") != "postgres":
            raise HTTPException(status_code=422, detail="Only local PostgreSQL SQL artifacts can be published to this Superset instance")
        sql = latest.content
        source_type = "sql_artifact"
    else:
        if artifact.artifact_type != "notebook":
            raise HTTPException(status_code=422, detail="Only notebook artifacts can be selected as notebooks")
        cells = json.loads(latest.content).get("cells", [])
        sql = next((str(cell.get("source", "")) for cell in reversed(cells) if cell.get("type") == "sql" and str(cell.get("source", "")).strip()), "")
        if not sql:
            raise HTTPException(status_code=422, detail="The notebook needs at least one saved SQL cell before it can be published")
        source_type = "notebook_sql_cell"

    if not _safe_read_only_sql(sql):
        raise HTTPException(status_code=400, detail="Only one read-only SELECT statement can be published")
    availability = superset_availability()
    if not availability["available"]:
        # Fail before creating an approval that could never be fulfilled.
        raise HTTPException(status_code=503, detail=f"Superset is unavailable: {availability['reason']}")
    try:
        preview = execute_read_only(engine, sql, 1)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Saved SQL is not executable in the local analytics database: {exc}") from exc

    job = Job(
        project_id=project.id,
        title=f"Publish analytics query: {(payload.name or artifact.name)[:160]}",
        job_type="superset_publish",
        status="WAITING_FOR_APPROVAL",
        progress=10,
        plan=[
            {"agent": "Governance", "action": "Validate immutable local SQL", "status": "complete"},
            {"agent": "Approver", "action": "Approve Superset virtual dataset publication", "status": "waiting"},
            {"agent": "Analytics", "action": "Register virtual dataset and embedded dashboard", "status": "pending"},
        ],
        evidence=[{"type": "artifact", "label": f"{artifact.name} v{latest.version}"}],
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    approval = Approval(
        project_id=project.id,
        job_id=job.id,
        title=job.title,
        action_type="publish_superset_query",
        risk_level="medium",
        evidence={
            "artifact_id": artifact.id,
            "artifact_version": latest.version,
            "source_type": source_type,
            "sql": sql,
            "name": (payload.name or artifact.name)[:160],
            "columns": preview["columns"],
            "summary": "Create a Superset virtual dataset backed by this immutable, locally validated SQL.",
            "checks": ["project ownership", "immutable artifact version", "read-only SQL", "local execution", "Superset approval required"],
        },
        requested_by=user.id,
    )
    db.add(approval)
    audit(db, user, "analytics.publication_requested", "artifact", artifact.id, {"approval_id": approval.id, "version": latest.version})
    db.commit()
    return {"approval_id": approval.id, "job_id": job.id, "status": "awaiting_approval"}


@router.get("/analytics/queries/{artifact_id}")
def get_query_analytics(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Report whether a saved SQL/notebook artifact has an approved, dedicated Superset dashboard.

    This is the read used by the SQL workspace and notebook editor to decide
    whether to show "Publish to Superset" (nothing approved yet) or "Open in
    Superset" (a dedicated dashboard already exists) next to a saved query —
    the hotlink from a governed result over to its own analytics view.
    """
    project = require_current_project(db, user)
    artifact = require_project_resource(db.get(Artifact, artifact_id), project, "Artifact")
    state = db.scalar(
        select(SupersetQueryDashboard).where(
            SupersetQueryDashboard.project_id == project.id,
            SupersetQueryDashboard.artifact_id == artifact.id,
        )
    )
    if state is None:
        return {"published": False, "artifact_id": artifact.id}
    return {
        "published": True,
        "artifact_id": artifact.id,
        "artifact_version": state.artifact_version,
        "dashboard_title": state.dashboard_title,
        "query_name": state.query_name,
        "superset_domain": os.getenv("SUPERSET_PUBLIC_URL", "http://localhost:8088").strip().rstrip("/"),
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


@router.post("/analytics/queries/{artifact_id}/guest-token")
def analytics_query_guest_token(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Mint a guest token for one artifact's own dedicated Superset dashboard.

    Distinct from POST /analytics/guest-token, which always targets the
    project's single primary dashboard. This re-runs the same idempotent
    ensure-dashboard/dataset provisioning as that endpoint, scoped to this
    artifact's dashboard_key, so a deleted/recreated Superset dashboard is
    transparently re-registered rather than returning a stale reference.
    """
    project = require_current_project(db, user)
    artifact = require_project_resource(db.get(Artifact, artifact_id), project, "Artifact")
    state = db.scalar(
        select(SupersetQueryDashboard).where(
            SupersetQueryDashboard.project_id == project.id,
            SupersetQueryDashboard.artifact_id == artifact.id,
        )
    )
    if state is None:
        raise HTTPException(status_code=409, detail="This query has not been approved for Superset publication yet")
    dataset = {
        "project_id": project.id,
        "project_slug": project.slug,
        "schema_name": "staging",
        "table_name": state.query_name,
        "columns": list(state.columns or []),
        "source_name": "DataPilot governed SQL",
        "asset_type": "virtual_query",
        "row_count": None,
        "sql": state.sql,
    }
    dashboard_key = f"query-{artifact.id}"
    if all(str(column.get("type", "text")) == "text" for column in dataset["columns"]):
        # Published before types were inferred: re-sample so charts use measures and time axes.
        try:
            dataset["columns"] = infer_column_types(execute_read_only(engine, state.sql, 200)) or dataset["columns"]
        except Exception:
            pass
    try:
        config = main.get_embed_configuration(project.name, project.slug, dataset, dashboard_key)
        token = create_guest_token(project.name, project.slug, dataset, user.id, user.email, user.name, dashboard_key)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=503, detail=f"Embedded analytics is unavailable: {exc}") from exc
    main.save_superset_query_dashboard_state(
        db, project, artifact, state.artifact_version, state.sql, list(state.columns or []), config, user.id
    )
    db.commit()
    return {
        "token": token["token"],
        "embedded_id": config["embedded_id"],
        "superset_domain": config["superset_domain"],
        "dashboard_title": config.get("dashboard_title", state.dashboard_title),
        "dataset_relation": config.get("dataset_relation"),
        "chart_count": config.get("chart_count"),
        "access_mode": config.get("access_mode"),
    }


@router.get("/analytics/status")
def analytics_status(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """Whether embedded analytics (Superset) is reachable, with guidance when it is not."""
    return superset_availability()


@router.get("/analytics/dashboards")
def analytics_dashboards(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Everything the current project can show in embedded analytics, in one list.

    Scope is the project: every entry belongs to the current project and is
    embedded with a guest token limited to that one dashboard. Entries are
    grouped by where the data comes from: the project's primary dashboard,
    approved published queries, and catalogued local datasets (by source).
    """
    from ..services.superset import local_analytics_datasets

    project = require_current_project(db, user)
    primary = db.scalar(select(SupersetProjectDashboard).where(SupersetProjectDashboard.project_id == project.id))
    try:
        default_dataset = resolve_superset_dataset(db, project)
        default_relation = f"{default_dataset['schema_name']}.{default_dataset['table_name']}"
    except ValueError:
        default_relation = None
    published = db.execute(
        select(SupersetQueryDashboard, Artifact)
        .join(Artifact, Artifact.id == SupersetQueryDashboard.artifact_id)
        .where(SupersetQueryDashboard.project_id == project.id)
        .order_by(SupersetQueryDashboard.updated_at.desc())
    ).all()
    datasets = local_analytics_datasets(db, project)
    return {
        "scope": "project",
        "project": {"id": project.id, "name": project.name},
        "superset": superset_availability(),
        "primary": {
            "key": "project",
            "title": (primary.dashboard_title if primary and primary.dashboard_title else f"{project.name} analytics"),
            "dataset_relation": default_relation,
            "chart_count": len(primary.chart_ids or []) if primary else None,
            "updated_at": primary.updated_at.isoformat() if primary and primary.updated_at else None,
            "available": default_relation is not None,
        },
        "published": [
            {
                "key": f"query:{artifact.id}",
                "artifact_id": artifact.id,
                "title": artifact.name,
                "artifact_type": artifact.artifact_type,
                "artifact_version": state.artifact_version,
                "columns": [str(column.get("name")) for column in state.columns or []],
                "chart_count": len(state.chart_ids or []),
                "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            }
            for state, artifact in published
        ],
        "datasets": [
            {
                "key": f"dataset:{asset.id}",
                "asset_id": asset.id,
                "relation": f"{asset.schema_name}.{asset.table_name}",
                "source": asset.source_name,
                "asset_type": asset.asset_type,
                "row_count": asset.row_count,
                "column_count": len(asset.columns or []),
                "sensitivity": asset.sensitivity,
                "is_default": f"{asset.schema_name}.{asset.table_name}" == default_relation,
                "restricted": asset.sensitivity == "restricted" and user.role != "admin",
            }
            for asset in sorted(datasets, key=lambda item: (item.source_name, item.schema_name, item.table_name))
        ],
    }


@router.post("/analytics/datasets/{asset_id}/guest-token")
def analytics_dataset_guest_token(asset_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Embed a dashboard built directly on one catalogued local dataset of the current project.

    Same trust model as the project dashboard (which is also built from a
    catalogued dataset without approval): project membership, local data only,
    no DataPilot metadata tables, restricted datasets for admins only, and
    PII-named columns left out of the charts.
    """
    from ..services.superset import dataset_dashboard_payload, local_analytics_datasets

    project = require_current_project(db, user)
    asset = next((item for item in local_analytics_datasets(db, project) if item.id == asset_id), None)
    if asset is None:
        raise HTTPException(status_code=404, detail="Dataset is not a local, queryable dataset of this project")
    if asset.sensitivity == "restricted" and user.role != "admin":
        raise HTTPException(status_code=403, detail="Restricted datasets can only be charted by an admin")
    availability = superset_availability()
    if not availability["available"]:
        raise HTTPException(status_code=503, detail=f"Superset is unavailable: {availability['reason']}")
    dataset = dataset_dashboard_payload(asset, project)
    if not dataset["columns"]:
        raise HTTPException(status_code=422, detail="Dataset has no chartable columns")
    dashboard_key = f"asset-{asset.id}"
    try:
        config = main.get_embed_configuration(project.name, project.slug, dataset, dashboard_key)
        token = create_guest_token(project.name, project.slug, dataset, user.id, user.email, user.name, dashboard_key)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=503, detail=f"Embedded analytics is unavailable: {exc}") from exc
    audit(db, user, "analytics.dataset_dashboard_opened", "data_asset", asset.id, {"dashboard_id": config.get("dashboard_id")})
    db.commit()
    return {
        "token": token["token"],
        "embedded_id": config["embedded_id"],
        "superset_domain": config["superset_domain"],
        "dashboard_title": config.get("dashboard_title"),
        "dataset_relation": config.get("dataset_relation"),
        "chart_count": config.get("chart_count"),
        "access_mode": config.get("access_mode"),
    }
