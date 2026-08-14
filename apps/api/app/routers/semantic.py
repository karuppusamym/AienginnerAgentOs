"""Auto-extracted semantic routes from the former monolithic main.py.

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
    require_current_project, require_data_editor, require_permission, require_project_resource,
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


@router.get("/semantic/graph")
def semantic_graph(
    include_inferred: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return the project relationship graph used by grounding and pipelines.

    Persisted edges are governed semantic join policies. Inferred edges are
    read-only suggestions based on matching column names and are never used
    for execution until a maintainer approves them.
    """
    project = require_current_project(db, user)
    assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project.id).order_by(DataAsset.table_name)).all()
    policies = db.scalars(select(SemanticJoinPolicy).where(SemanticJoinPolicy.project_id == project.id)).all()
    # Two different sources can legitimately catalog a table under the same
    # schema.table name (e.g. a locally-seeded "core.accounts" demo table and
    # an externally-scanned "core.accounts" from a SQL Server connector are
    # both real, distinct DataAsset rows — this isn't a data bug). The graph
    # used to label both nodes with the bare "schema.table" string, so they
    # were visually and even on-hover indistinguishable — a real UX gap
    # noticed live in this project's own graph (two identical "core.accounts"
    # nodes). Disambiguate only the relations that actually collide, so every
    # already-unique relation keeps its plain, familiar label.
    connector_names = {connector.id: connector.name for connector in db.scalars(select(Connector).where(Connector.project_id == project.id)).all()}
    bare_relations = [f"{asset.schema_name}.{asset.table_name}" for asset in assets]
    duplicate_relations = {relation for relation in bare_relations if bare_relations.count(relation) > 1}
    nodes = []
    for asset, bare_relation in zip(assets, bare_relations):
        relation = bare_relation
        if bare_relation in duplicate_relations:
            source_label = connector_names.get(asset.connector_id, "local catalog") if asset.connector_id else "local catalog"
            relation = f"{bare_relation} ({source_label})"
        nodes.append({"id": asset.id, "relation": relation, "columns": column_names_for_asset(asset), "metadata_status": asset.metadata_status})
    edges = [{"id": policy.id, "source": policy.left_asset_id, "target": policy.right_asset_id, "left_column": policy.left_column, "right_column": policy.right_column, "join_type": policy.join_type, "status": policy.status, "governed": True} for policy in policies]
    if include_inferred:
        for index, left in enumerate(assets):
            left_columns = set(column_names_for_asset(left))
            for right in assets[index + 1:]:
                shared = sorted(left_columns & set(column_names_for_asset(right)))
                for column in shared:
                    if column.lower() in {"id", "created_at", "updated_at"}:
                        continue
                    if any({edge["source"], edge["target"]} == {left.id, right.id} and edge["left_column"] == column and edge["right_column"] == column for edge in edges):
                        continue
                    edges.append({"id": f"inferred:{left.id}:{right.id}:{column}", "source": left.id, "target": right.id, "left_column": column, "right_column": column, "join_type": "inner", "status": "suggested", "governed": False})
    return {"project_id": project.id, "nodes": nodes, "edges": edges, "governed_edge_count": sum(1 for edge in edges if edge["governed"]), "inferred_edge_count": sum(1 for edge in edges if not edge["governed"])}


@router.get("/semantic/metrics")
def list_semantic_metrics(
    project_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    membership = main.current_membership(db, user)
    resolved_project_id = project_id or (membership.project_id if membership else None)
    if resolved_project_id is None:
        return []
    require_permission(user, db, "semantic:read", "Project membership required")
    metrics = db.scalars(select(SemanticMetric).where(SemanticMetric.project_id == resolved_project_id).order_by(SemanticMetric.name)).all()
    return [as_dict(metric, ["id", "project_id", "asset_id", "name", "description", "formula", "grain", "owner", "dimensions", "synonyms", "status", "created_at", "updated_at"]) for metric in metrics]

@router.post("/semantic/metrics", status_code=201)
def create_semantic_metric(
    payload: SemanticMetricCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    membership = main.current_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=409, detail="Select a project first")
    require_permission(user, db, "semantic:write", "Project maintainer access required")
    if payload.asset_id:
        asset = db.get(DataAsset, payload.asset_id)
        if asset is None or asset.project_id != membership.project_id:
            raise HTTPException(status_code=404, detail="Metric dataset not found in the current project")
    metric = SemanticMetric(project_id=membership.project_id, created_by=user.id, **payload.model_dump())
    db.add(metric)
    db.flush()
    audit(db, user, "semantic_metric.created", "semantic_metric", metric.id, {"project_id": metric.project_id})
    db.commit()
    return as_dict(metric, ["id", "project_id", "asset_id", "name", "description", "formula", "grain", "owner", "dimensions", "synonyms", "status", "created_at", "updated_at"])

@router.put("/semantic/metrics/{metric_id}")
def update_semantic_metric(
    metric_id: str,
    payload: SemanticMetricCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    metric = db.get(SemanticMetric, metric_id)
    membership = main.current_membership(db, user)
    if metric is None:
        raise HTTPException(status_code=404, detail="Metric not found")
    if membership is None or metric.project_id != membership.project_id:
        raise HTTPException(status_code=403, detail="Project maintainer access required")
    require_permission(user, db, "semantic:write", "Project maintainer access required")
    if payload.asset_id:
        asset = db.get(DataAsset, payload.asset_id)
        if asset is None or asset.project_id != metric.project_id:
            raise HTTPException(status_code=404, detail="Metric dataset not found in the current project")
    for field, value in payload.model_dump().items():
        setattr(metric, field, value)
    audit(db, user, "semantic_metric.updated", "semantic_metric", metric.id)
    db.commit()
    return as_dict(metric, ["id", "project_id", "asset_id", "name", "description", "formula", "grain", "owner", "dimensions", "synonyms", "status", "created_at", "updated_at"])

@router.delete("/semantic/metrics/{metric_id}")
def delete_semantic_metric(
    metric_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    metric = db.get(SemanticMetric, metric_id)
    membership = main.current_membership(db, user)
    if metric is None:
        raise HTTPException(status_code=404, detail="Metric not found")
    if membership is None or metric.project_id != membership.project_id:
        raise HTTPException(status_code=403, detail="Project maintainer access required")
    require_permission(user, db, "semantic:write", "Project maintainer access required")
    audit(db, user, "semantic_metric.deleted", "semantic_metric", metric.id)
    db.delete(metric)
    db.commit()
    return {"id": metric_id, "status": "deleted"}

@router.get("/semantic/joins")
def list_semantic_join_policies(
    project_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    membership = main.current_membership(db, user)
    resolved_project_id = project_id or (membership.project_id if membership else None)
    if resolved_project_id is None:
        return []
    require_permission(user, db, "semantic:read", "Project membership required")
    policies = db.scalars(select(SemanticJoinPolicy).where(SemanticJoinPolicy.project_id == resolved_project_id).order_by(SemanticJoinPolicy.updated_at.desc())).all()
    return [semantic_join_policy_output(policy) for policy in policies]

@router.post("/semantic/joins", status_code=201)
def create_semantic_join_policy(
    payload: SemanticJoinPolicyCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    membership = main.current_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=409, detail="Select a project first")
    require_semantic_maintainer(db, user, membership.project_id)
    validate_semantic_join_policy(db, membership.project_id, payload)
    existing = db.scalars(
        select(SemanticJoinPolicy).where(SemanticJoinPolicy.project_id == membership.project_id)
    ).all()
    if any(
        {item.left_asset_id, item.right_asset_id} == {payload.left_asset_id, payload.right_asset_id}
        and {item.left_column, item.right_column} == {payload.left_column, payload.right_column}
        for item in existing
    ):
        raise HTTPException(status_code=409, detail="An equivalent join policy already exists for these datasets and columns")
    policy = SemanticJoinPolicy(project_id=membership.project_id, created_by=user.id, **payload.model_dump())
    db.add(policy)
    db.flush()
    audit(db, user, "semantic_join_policy.created", "semantic_join_policy", policy.id, {"project_id": policy.project_id, "status": policy.status})
    db.commit()
    return semantic_join_policy_output(policy)

@router.put("/semantic/joins/{policy_id}")
def update_semantic_join_policy(
    policy_id: str,
    payload: SemanticJoinPolicyCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    policy = db.get(SemanticJoinPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Join policy not found")
    require_semantic_maintainer(db, user, policy.project_id)
    validate_semantic_join_policy(db, policy.project_id, payload)
    for field, value in payload.model_dump().items():
        setattr(policy, field, value)
    audit(db, user, "semantic_join_policy.updated", "semantic_join_policy", policy.id, {"status": policy.status})
    db.commit()
    return semantic_join_policy_output(policy)

@router.delete("/semantic/joins/{policy_id}")
def delete_semantic_join_policy(
    policy_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    policy = db.get(SemanticJoinPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Join policy not found")
    require_semantic_maintainer(db, user, policy.project_id)
    audit(db, user, "semantic_join_policy.deleted", "semantic_join_policy", policy.id)
    db.delete(policy)
    db.commit()
    return {"id": policy_id, "status": "deleted"}
