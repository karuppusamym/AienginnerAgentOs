"""Auto-extracted query_tools routes from the former monolithic main.py.

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


@router.get("/query-tools/relation-options")
def list_query_tool_relation_options(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    assets = db.scalars(
        select(DataAsset)
        .where(DataAsset.project_id == project.id)
        .order_by(DataAsset.schema_name, DataAsset.table_name)
    ).all()
    options = []
    for asset in assets:
        connector = db.get(Connector, asset.connector_id) if asset.connector_id else None
        relation, _ = _asset_relation_sql(asset, connector)
        options.append(
            {
                "asset_id": asset.id,
                "relation": relation,
                "source_name": asset.source_name,
                "connector_id": asset.connector_id,
                "connector_name": connector.name if connector else "DataPilot local staging",
                "columns": asset.columns,
                "tags": asset.tags,
            }
        )
    return options

@router.post("/query-tools/wizard/preview")
def preview_query_tool_wizard(
    payload: QueryToolWizardPreview,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    asset = require_project_resource(db.get(DataAsset, payload.asset_id), project, "Data asset")
    connector = require_project_resource(db.get(Connector, asset.connector_id), project, "Connector") if asset.connector_id else None
    relation, relation_sql = _asset_relation_sql(asset, connector)
    columns = {str(column.get("name")): column for column in asset.columns}
    dialect = connector_dialect(connector, "postgres")
    row_limiter = "FETCH FIRST 100 ROWS ONLY" if dialect in {"oracle", "teradata"} else "LIMIT 100"
    if payload.template == "record_lookup":
        column_name = payload.key_column or next(iter(columns), "")
        if column_name not in columns:
            raise HTTPException(status_code=400, detail="The selected key column is not part of the asset")
        sql_template = f"SELECT * FROM {relation_sql} WHERE {_identifier_quote(column_name, dialect)} = :lookup_value " + ("FETCH FIRST 1 ROWS ONLY" if dialect in {"oracle", "teradata"} else "LIMIT 1")
        parameter_schema = {"type": "object", "required": ["lookup_value"], "properties": {"lookup_value": {"type": _json_schema_type(columns[column_name])}}, "additionalProperties": False}
        suffix, description = "lookup", f"Read one {asset.table_name} record by {column_name}."
    elif payload.template == "filtered_count":
        column_name = payload.filter_column or next(iter(columns), "")
        if column_name not in columns:
            raise HTTPException(status_code=400, detail="The selected filter column is not part of the asset")
        sql_template = f"SELECT COUNT(*) AS total FROM {relation_sql} WHERE {_identifier_quote(column_name, dialect)} = :filter_value"
        parameter_schema = {"type": "object", "required": ["filter_value"], "properties": {"filter_value": {"type": _json_schema_type(columns[column_name])}}, "additionalProperties": False}
        suffix, description = "count_by_filter", f"Count {asset.table_name} records by {column_name}."
    else:
        column_name = payload.time_column or next(iter(columns), "")
        if column_name not in columns:
            raise HTTPException(status_code=400, detail="The selected time column is not part of the asset")
        sql_template = f"SELECT * FROM {relation_sql} ORDER BY {_identifier_quote(column_name, dialect)} DESC {row_limiter}"
        parameter_schema = {"type": "object", "properties": {}, "additionalProperties": False}
        suffix, description = "recent_records", f"Return the most recent {asset.table_name} records ordered by {column_name}."
    return {
        "asset": {"id": asset.id, "relation": relation, "connector_id": asset.connector_id, "dialect": dialect},
        "suggested_tool": {
            "name": f"{safe_identifier(asset.table_name, 'dataset')}.{suffix}",
            "description": description,
            "purpose": description,
            "data_source": asset.source_name,
            "line_of_business": "Unassigned",
            "owner": "Unassigned",
            "tags": list(dict.fromkeys([*asset.tags, "read-only", "wizard-generated"])),
            "connector_id": asset.connector_id,
            "upstream_tool_name": None,
            "sql_template": sql_template,
            "parameter_schema": parameter_schema,
            "result_schema": {"type": "object"},
            "allowed_relations": [relation],
            "row_limit": 100 if payload.template == "recent_records" else 1 if payload.template == "record_lookup" else 200,
            "timeout_seconds": 15,
            "requires_approval": False,
        },
    }

@router.get("/external-clients")
def list_external_clients(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, admin)
    clients = db.scalars(select(ExternalClient).where(ExternalClient.default_project_id == project.id).order_by(ExternalClient.created_at.desc())).all()
    return [external_client_output(client) for client in clients]

@router.post("/external-clients", status_code=201)
def create_external_client(payload: ExternalClientCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, admin)
    client_id = f"dp_{secrets.token_hex(8)}"
    secret = secrets.token_urlsafe(32)
    client = ExternalClient(name=payload.name, client_id=client_id, secret_hash=hash_password(secret), scopes=list(dict.fromkeys(payload.scopes)), default_project_id=project.id, created_by=admin.id)
    db.add(client)
    db.flush()
    audit(db, admin, "external_client.created", "external_client", client.id, {"scopes": client.scopes})
    db.commit()
    return {**external_client_output(client), "token": f"{client_id}.{secret}"}

@router.put("/external-clients/{client_id}")
def update_external_client(client_id: str, payload: ExternalClientUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, admin)
    client = db.get(ExternalClient, client_id)
    if client is None or client.default_project_id != project.id:
        raise HTTPException(status_code=404, detail="External client not found")
    client.active = payload.active
    client.scopes = list(dict.fromkeys(payload.scopes))
    audit(db, admin, "external_client.updated", "external_client", client.id, {"active": client.active, "scopes": client.scopes})
    db.commit()
    return external_client_output(client)

@router.post("/external-clients/{client_id}/rotate")
def rotate_external_client(client_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, admin)
    client = db.get(ExternalClient, client_id)
    if client is None or client.default_project_id != project.id:
        raise HTTPException(status_code=404, detail="External client not found")
    secret = secrets.token_urlsafe(32)
    client.secret_hash = hash_password(secret)
    audit(db, admin, "external_client.rotated", "external_client", client.id)
    db.commit()
    return {**external_client_output(client), "token": f"{client.client_id}.{secret}"}

@router.get("/query-tools")
def list_query_tools(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    tools = db.scalars(select(QueryTool).where(QueryTool.project_id == project.id).order_by(QueryTool.updated_at.desc())).all()
    return [query_tool_output(tool) for tool in tools]

@router.get("/query-tools/summary")
def query_tool_registry_summary(
    admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    project = require_current_project(db, admin)
    tools = db.scalars(select(QueryTool).where(QueryTool.project_id == project.id).order_by(QueryTool.name)).all()
    items = [{**query_tool_output(tool), **query_tool_usage_summary(db, tool)} for tool in tools]
    return {
        "total": len(items),
        "published": sum(1 for item in items if item["status"] == "published"),
        "draft": sum(1 for item in items if item["status"] == "draft"),
        "never_invoked": sum(1 for item in items if item["invocation_count"] == 0),
        "tools": items,
    }

@router.get("/query-tools/{tool_id}/analytics")
def query_tool_analytics(
    tool_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, admin)
    tool = db.get(QueryTool, tool_id)
    if tool is None or tool.project_id != project.id:
        raise HTTPException(status_code=404, detail="Query tool not found")
    return {"tool": query_tool_output(tool), **query_tool_usage_summary(db, tool)}

@router.post("/query-tools", status_code=201)
def create_query_tool(payload: QueryToolCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_permission(user, db, "registry:write", "Registry write permission required")
    project = require_current_project(db, user)
    _validate_query_tool_contract(payload, db, project)
    if db.scalar(select(QueryTool).where(QueryTool.project_id == project.id, QueryTool.name == payload.name)):
        raise HTTPException(status_code=409, detail="A query tool with this name already exists")
    values = payload.model_dump()
    values["tags"] = list(dict.fromkeys(tag.strip().lower() for tag in payload.tags if tag.strip()))
    tool = QueryTool(project_id=project.id, created_by=user.id, **values)
    db.add(tool)
    db.flush()
    audit(db, user, "query_tool.created", "query_tool", tool.id)
    db.commit()
    return query_tool_output(tool)

@router.put("/query-tools/{tool_id}")
def update_query_tool(tool_id: str, payload: QueryToolCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_permission(user, db, "registry:write", "Registry write permission required")
    project = require_current_project(db, user)
    tool = db.get(QueryTool, tool_id)
    if tool is None or tool.project_id != project.id:
        raise HTTPException(status_code=404, detail="Query tool not found")
    _validate_query_tool_contract(payload, db, project)
    duplicate = db.scalar(select(QueryTool).where(QueryTool.project_id == project.id, QueryTool.name == payload.name, QueryTool.id != tool.id))
    if duplicate:
        raise HTTPException(status_code=409, detail="A query tool with this name already exists")
    values = payload.model_dump()
    values["tags"] = list(dict.fromkeys(tag.strip().lower() for tag in payload.tags if tag.strip()))
    for field, value in values.items():
        setattr(tool, field, value)
    tool.status = "draft"
    tool.version += 1
    audit(db, user, "query_tool.version_created", "query_tool", tool.id, {"version": tool.version})
    db.commit()
    return query_tool_output(tool)

@router.post("/query-tools/{tool_id}/publish")
def publish_query_tool(tool_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, admin)
    tool = db.get(QueryTool, tool_id)
    if tool is None or tool.project_id != project.id:
        raise HTTPException(status_code=404, detail="Query tool not found")
    tool.status = "published"
    audit(db, admin, "query_tool.published", "query_tool", tool.id, {"version": tool.version})
    db.commit()
    return query_tool_output(tool)

@router.post("/query-tools/{tool_id}/grants", status_code=201)
def grant_query_tool(tool_id: str, payload: QueryToolGrantCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, admin)
    tool = db.get(QueryTool, tool_id)
    client = db.get(ExternalClient, payload.external_client_id)
    if tool is None or tool.project_id != project.id:
        raise HTTPException(status_code=404, detail="Query tool not found")
    if client is None or client.default_project_id != project.id:
        raise HTTPException(status_code=404, detail="External client not found")
    grant = db.scalar(select(QueryToolGrant).where(QueryToolGrant.query_tool_id == tool.id, QueryToolGrant.external_client_id == client.id))
    if grant is None:
        grant = QueryToolGrant(project_id=project.id, query_tool_id=tool.id, external_client_id=client.id, enabled=payload.enabled, created_by=admin.id)
        db.add(grant)
    else:
        grant.enabled = payload.enabled
    audit(db, admin, "query_tool.grant_updated", "query_tool", tool.id, {"external_client_id": client.id, "enabled": grant.enabled})
    db.commit()
    return as_dict(grant, ["id", "project_id", "query_tool_id", "external_client_id", "enabled", "created_at"])

@router.post("/query-tools/{tool_id}/test")
def test_query_tool(tool_id: str, payload: QueryToolInvoke, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    tool = db.get(QueryTool, tool_id)
    if tool is None or tool.project_id != project.id:
        raise HTTPException(status_code=404, detail="Query tool not found")
    _validate_tool_parameters(tool.parameter_schema, payload.parameters)
    try:
        if tool.connector_id:
            connector = require_project_resource(db.get(Connector, tool.connector_id), project, "Connector")
            result = main.execute_connector_query(
                connector, tool.sql_template, payload.parameters, tool.row_limit, tool.timeout_seconds,
                upstream_tool_name=tool.upstream_tool_name,
                user_id=user.id,
                session_id=tool.id,
                feature="query_tool_test",
            )
        else:
            result = execute_parameterized_read_only(engine, tool.sql_template, payload.parameters, tool.row_limit, tool.timeout_seconds)
    except HTTPException:
        raise
    except Exception as exc:
        # Bug fix: this endpoint used to let any connector/execution failure
        # (bad/missing credentials, unreachable host, a query tool built
        # against an offline demo-only connector, etc.) propagate as a bare,
        # unhandled 500 "Internal Server Error" with zero diagnostic detail --
        # found live while testing "transactions.lookup" against the
        # "Banking demo warehouse" connector, which has no secret_reference
        # configured (it's a schema-browsing-only demo connector, not one
        # wired for live execution). The external invoke path
        # (_invoke_external_query_tool in main.py) already converts the same
        # class of failure into an informative 422; mirror that here so the
        # Catalog wizard's own "Test" button surfaces an actionable message
        # instead of a dead end.
        raise HTTPException(status_code=422, detail=f"Query tool test failed: {exc}") from exc
    audit(db, user, "query_tool.tested", "query_tool", tool.id, {"row_count": result["row_count"]})
    if tool.status == "draft":
        tool.status = "tested"
    db.commit()
    return result


@router.post("/query-tools/{tool_id}/retire")
def retire_query_tool(tool_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, admin)
    tool = db.get(QueryTool, tool_id)
    if tool is None or tool.project_id != project.id:
        raise HTTPException(status_code=404, detail="Query tool not found")
    tool.status = "retired"
    audit(db, admin, "query_tool.retired", "query_tool", tool.id, {"version": tool.version})
    db.commit()
    return query_tool_output(tool)

@router.get("/external-invocations")
def list_external_invocations(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, admin)
    invocations = db.scalars(select(ExternalInvocation).where(ExternalInvocation.project_id == project.id).order_by(ExternalInvocation.created_at.desc()).limit(200)).all()
    return [as_dict(item, ["id", "project_id", "external_client_id", "query_tool_id", "status", "parameters", "result_metadata", "error", "duration_ms", "created_at"]) for item in invocations]

@router.get("/external/v1/query-tools")
def search_external_query_tools(
    q: str = Query(default="", max_length=500),
    data_source: str = Query(default="", max_length=160),
    line_of_business: str = Query(default="", max_length=160),
    tag: str = Query(default="", max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    client = _external_client_from_header(authorization, db, "tools:list")
    tools = _filter_registry_tools(
        _granted_query_tools(db, client), q, data_source, line_of_business, tag
    )[:limit]
    return {"tools": [_external_query_tool_output(tool) for tool in tools], "count": len(tools)}

@router.get("/external/v1/query-tools/{tool_name}")
def get_external_query_tool(
    tool_name: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    client = _external_client_from_header(authorization, db, "tools:list")
    tool = next((item for item in _granted_query_tools(db, client) if item.name == tool_name), None)
    if tool is None:
        raise HTTPException(status_code=404, detail="Published query tool not found")
    return _external_query_tool_output(tool)

@router.post("/external/v1/query-tools/{tool_name}/invoke")
def invoke_external_query_tool(tool_name: str, payload: QueryToolInvoke, authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict[str, Any]:
    client = _external_client_from_header(authorization, db, "tools:invoke")
    tool = db.scalar(select(QueryTool).where(QueryTool.project_id == client.default_project_id, QueryTool.name == tool_name))
    if tool is None:
        raise HTTPException(status_code=404, detail="Published query tool not found")
    return _invoke_external_query_tool(db, client, tool, payload.parameters)

@router.get("/external/v1/openapi.json")
def external_openapi(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict[str, Any]:
    client = _external_client_from_header(authorization, db, "tools:list")
    paths: dict[str, Any] = {}
    for tool in _granted_query_tools(db, client):
        paths[f"/external/v1/query-tools/{tool.name}/invoke"] = {
            "post": {
                "operationId": tool.name.replace(".", "_"),
                "summary": tool.description,
                "description": tool.purpose,
                "x-datapilot-registry": _registry_metadata(tool),
                "security": [{"bearerAuth": []}],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "properties": {"parameters": tool.parameter_schema}, "required": ["parameters"]}}}},
                "responses": {"200": {"description": "Bounded query result"}},
            }
        }
    return {"openapi": "3.1.0", "info": {"title": "DataPilot governed query tools", "version": "1.0.0"}, "paths": paths, "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}}}

@router.get("/.well-known/mcp.json")
def mcp_metadata() -> dict[str, Any]:
    return {"name": "DataPilot governed query tools", "protocolVersion": "2025-03-26", "transport": {"type": "streamable-http", "url": "/mcp"}, "authentication": {"type": "bearer"}}

@router.post("/mcp")
def mcp_endpoint(payload: MCPRequest, authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        if payload.method == "initialize":
            _external_client_from_header(authorization, db, "tools:list")
            result: dict[str, Any] = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "DataPilot", "version": "1.0.0"}}
        elif payload.method == "tools/list":
            client = _external_client_from_header(authorization, db, "tools:list")
            tools = _filter_registry_tools(
                _granted_query_tools(db, client),
                str(payload.params.get("q") or payload.params.get("query") or ""),
                str(payload.params.get("data_source") or ""),
                str(payload.params.get("line_of_business") or ""),
                str(payload.params.get("tag") or ""),
            )
            result = {"tools": [{
                "name": tool.name,
                "title": tool.purpose,
                "description": tool.description,
                "inputSchema": tool.parameter_schema,
                "outputSchema": tool.result_schema,
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
                "_meta": {"com.datapilot.registry": _registry_metadata(tool)},
            } for tool in tools]}
        elif payload.method == "tools/call":
            client = _external_client_from_header(authorization, db, "tools:invoke")
            name = str(payload.params.get("name", ""))
            tool = db.scalar(select(QueryTool).where(QueryTool.project_id == client.default_project_id, QueryTool.name == name))
            if tool is None:
                raise HTTPException(status_code=404, detail="Published query tool not found")
            invoked = _invoke_external_query_tool(db, client, tool, payload.params.get("arguments", {}))
            result = {"content": [{"type": "text", "text": json.dumps(invoked, default=str)}], "structuredContent": invoked, "isError": False}
        elif payload.method == "notifications/initialized":
            return {"jsonrpc": "2.0", "result": {}}
        else:
            return {"jsonrpc": "2.0", "id": payload.id, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": payload.id, "result": result}
    except HTTPException as exc:
        return {"jsonrpc": "2.0", "id": payload.id, "error": {"code": -32000, "message": str(exc.detail), "data": {"http_status": exc.status_code}}}
