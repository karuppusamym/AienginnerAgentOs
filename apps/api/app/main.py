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

from .auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from .governance import initialize_governance, record_audit_event, record_governance_event, record_governance_score
from .rate_limit import check_rate_limit
from .connector_runtime import ConnectorRuntimeError, execute_connector_query, test_connection
from .connection_guard import ConnectionLimitExceeded
from .database import Base, SessionLocal, engine, get_db
from .demo_data import ensure_demo_tables
from .file_profiles import profile_file, read_structured_rows
from .grounding import context_signature, grounding_context, grounding_prompt_text, normalize_query, project_grounding_signature
from .model_runtime import generate_text, test_provider as invoke_provider_test
from .metadata_scan_runtime import execute_metadata_scan
from .models import (
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
    QueryRun,
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
from .provider_selection import current_membership, selected_model_provider
from .quality import execute_quality_rule
from .notebook_runtime import execute_notebook
from .observability import elapsed_ms, emit, initialize_observability, request_id, span, status as observability_status
from .pipeline_codegen import (
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
from .schedule_runtime import next_run_at, run_ingestion_schedule
from .schema_migrations import backfill_project_columns, ensure_project_columns
from .seed import seed_database
from .staging import execute_parameterized_read_only, execute_read_only, safe_identifier, stage_rows
from .superset_client import create_editor_url, create_guest_token, get_embed_configuration
from .temporal_activities import run_agent_plan_locally
from .temporal_runtime import cancel_workflow, start_agent_workflow, start_metadata_scan_workflow, start_scheduled_ingestion_workflow
from .tool_runtime import ToolRuntimeError, execute_tool
from .vector_store import index_document, search_documents


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def startup() -> None:
    initialize_observability()
    initialize_governance()
    Base.metadata.create_all(bind=engine)
    ensure_project_columns(engine)
    if os.getenv("ENABLE_DEMO_DATA", "false").lower() in {"1", "true", "yes"}:
        ensure_demo_tables(engine)
    with SessionLocal() as db:
        seed_database(db)
        default_project = db.scalar(select(Project).order_by(Project.created_at))
        if default_project:
            backfill_project_columns(engine, default_project.id)
            db.expire_all()
        assets = db.scalars(select(DataAsset)).all()
        for asset in assets:
            try:
                index_document(
                    asset.id,
                    f"{asset.schema_name}.{asset.table_name}",
                    f"{asset.description or ''} Columns: "
                    + ", ".join(column.get("name", "") for column in asset.columns),
                    {
                        "source_type": "dataset",
                        "schema_name": asset.schema_name,
                        "table_name": asset.table_name,
                        "tags": asset.tags,
                    },
                )
            except Exception:
                pass


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    startup()
    yield


app = FastAPI(
    title="DataPilot Agent OS API",
    version="0.1.0",
    description="Local-first governed AI data engineering workspace.",
    lifespan=app_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    # Developers commonly get the next available Next.js port (3001/3002).
    # Keep the local defaults aligned with the Compose web service without
    # opening CORS to arbitrary origins.
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:3002").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observe_request(request: Request, call_next: Any) -> Any:
    supplied_request_id = request.headers.get("X-Request-ID", "")
    # Request IDs are echoed to clients and emitted in structured logs.  Accept a
    # portable trace identifier, but never let arbitrary header content become a
    # log value or a response header.
    correlation_id = (
        supplied_request_id
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_request_id)
        else str(uuid4())
    )
    token = request_id.set(correlation_id)
    started = time.perf_counter()
    try:
        with span("http.request", method=request.method, path=request.url.path):
            response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        # These API-safe defaults protect browser consumers without changing CORS
        # behavior or the interactive OpenAPI documentation.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        duration_ms = elapsed_ms(started)
        emit("http.request", method=request.method, path=request.url.path, status=response.status_code, duration_ms=duration_ms)
        record_governance_event(
            "http_request",
            f"{request.method} {request.url.path}",
            "succeeded" if response.status_code < 400 else "rejected" if response.status_code < 500 else "failed",
            session_id=correlation_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
    except Exception as exc:
        duration_ms = elapsed_ms(started)
        emit("http.request.failed", method=request.method, path=request.url.path, duration_ms=duration_ms)
        record_governance_event(
            "http_request",
            f"{request.method} {request.url.path}",
            "failed",
            session_id=correlation_id,
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
        )
        raise
    finally:
        request_id.reset(token)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    name: str
    role: Literal["admin", "engineer", "analyst", "viewer"] = "analyst"
    temporary_password: str = Field(min_length=10)


class UserUpdate(BaseModel):
    role: Literal["admin", "engineer", "analyst", "viewer"] | None = None
    active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=500)


class ProviderCreate(BaseModel):
    name: str
    provider_type: Literal[
        "company_gateway", "gemini", "openai", "claude", "openai_compatible", "local_mock"
    ]
    base_url: str | None = None
    default_model: str
    embedding_model: str | None = None
    secret_reference: str | None = None
    enabled: bool = True
    is_default: bool = False


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, min_length=1, max_length=160)
    embedding_model: str | None = Field(default=None, max_length=160)
    secret_reference: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    environment: str = Field(default="local", min_length=1, max_length=40)


class ProjectMemberUpdate(BaseModel):
    user_id: str
    role: Literal["owner", "maintainer", "member", "viewer"] = "member"


class ProjectModelUpdate(BaseModel):
    provider_id: str


class SemanticMetricCreate(BaseModel):
    asset_id: str | None = None
    name: str = Field(min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=5_000)
    formula: str = Field(min_length=1, max_length=10_000)
    grain: str = Field(min_length=1, max_length=255)
    owner: str = Field(min_length=1, max_length=160)
    dimensions: list[str] = Field(default_factory=list, max_length=100)
    synonyms: list[str] = Field(default_factory=list, max_length=100)
    status: Literal["draft", "approved", "deprecated"] = "draft"


class SemanticJoinPolicyCreate(BaseModel):
    left_asset_id: str
    right_asset_id: str
    left_column: str = Field(min_length=1, max_length=160)
    right_column: str = Field(min_length=1, max_length=160)
    join_type: Literal["inner", "left"] = "inner"
    description: str | None = Field(default=None, max_length=5_000)
    status: Literal["draft", "approved", "deprecated"] = "draft"


class FeedbackCreate(BaseModel):
    context_type: Literal["sql", "agent_run", "artifact", "dataset", "notebook"]
    context_id: str | None = Field(default=None, max_length=80)
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = Field(default=None, max_length=5_000)


class ConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    connector_type: Literal["postgres", "sql_server", "oracle", "teradata", "bigquery", "local_files"]
    description: str | None = Field(default=None, max_length=5_000)
    connection_mode: Literal["direct", "mcp"] = "direct"
    host: str | None = None
    database: str | None = None
    mcp_server_url: str | None = Field(default=None, max_length=2_000)
    secret_reference: str | None = None
    read_only: bool = True


class DataAssetUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=5_000)
    tags: list[str] | None = Field(default=None, max_length=32)
    owner: str | None = Field(default=None, max_length=160)
    sensitivity: Literal["unclassified", "internal", "confidential", "restricted"] | None = None
    freshness_sla_hours: int | None = Field(default=None, ge=1, le=8760)
    metadata_status: Literal["scanned", "reviewed", "certified", "deprecated"] | None = None
    # Keyed by physical column name -> {"business_name": ..., "description": ...}.
    # DataAsset.columns entries otherwise only ever have name/type/nullable —
    # there was no way to record what a column *means* in business terms, only
    # a single free-text description for the whole table. Partial: only the
    # column names present as keys are touched: everything else is left alone.
    column_notes: dict[str, dict[str, str]] | None = Field(default=None)


class ConnectorUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    connector_type: Literal["postgres", "sql_server", "oracle", "teradata", "bigquery", "local_files"]
    description: str | None = Field(default=None, max_length=5_000)
    connection_mode: Literal["direct", "mcp"] = "direct"
    host: str | None = None
    database: str | None = None
    mcp_server_url: str | None = Field(default=None, max_length=2_000)
    secret_reference: str | None = None
    read_only: bool = True


class QueryToolWizardPreview(BaseModel):
    asset_id: str
    template: Literal["record_lookup", "filtered_count", "recent_records"]
    key_column: str | None = Field(default=None, max_length=160)
    filter_column: str | None = Field(default=None, max_length=160)
    time_column: str | None = Field(default=None, max_length=160)


class ExternalExtractionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    connector_id: str
    source_asset_id: str
    target_table: str = Field(min_length=1, max_length=160)
    load_mode: Literal["append", "replace", "upsert"] = "append"
    key_columns: list[str] = Field(default_factory=list, max_length=20)
    watermark_column: str | None = Field(default=None, max_length=160)
    batch_limit: int = Field(default=5_000, ge=1, le=10_000)


class SQLRequest(BaseModel):
    question: str
    connector_id: str | None = None
    dialect: Literal["sqlserver", "oracle", "teradata", "bigquery", "postgres"] = "sqlserver"
    # A bounded, server-supplied transcript lets a follow-up keep its analysis
    # context without turning the SQL endpoint into a client-controlled memory store.
    conversation_context: list[dict[str, str]] = Field(default_factory=list, max_length=16)


class SQLExecutionRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    dialect: Literal["postgres"] = "postgres"
    limit: int = Field(default=500, ge=1, le=1000)


class SupersetPublishRequest(BaseModel):
    """Request promotion of immutable, local read-only SQL to analytics.

    Publication is deliberately an approval-gated action: the SQL is stored in
    the approval evidence, revalidated when approved, and then registered as a
    Superset virtual dataset.  This avoids a UI-only handoff and prevents an
    editor from silently changing the query between review and publication.
    """

    artifact_id: str | None = None
    notebook_id: str | None = None
    name: str | None = Field(default=None, max_length=160)


class ArtifactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    artifact_type: Literal["sql", "workflow", "quality_rule", "prompt", "runbook", "notebook", "evaluation", "report"]
    content: str = Field(min_length=1, max_length=500_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifact_id: str | None = None


class MappingColumn(BaseModel):
    source_name: str = Field(min_length=1, max_length=200)
    target_name: str = Field(min_length=1, max_length=160)
    target_type: Literal["string", "integer", "number", "boolean"]
    nullable: bool = True


class SchemaMappingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_table: str = Field(min_length=1, max_length=160)
    columns: list[MappingColumn] = Field(min_length=1, max_length=500)
    mapping_id: str | None = None


class FileStageRequest(BaseModel):
    mapping_id: str
    load_mode: Literal["versioned", "replace", "append", "upsert"] = "versioned"
    key_columns: list[str] = Field(default_factory=list, max_length=20)


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mapping_id: str
    cron: str = Field(min_length=5, max_length=100)
    timezone: str = Field(default="UTC", max_length=80)
    load_mode: Literal["append", "upsert"] = "append"
    key_columns: list[str] = Field(default_factory=list, max_length=20)
    watermark_column: str | None = Field(default=None, max_length=160)


class ArtifactCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    version: int | None = Field(default=None, ge=1)


class ArtifactReviewRequest(BaseModel):
    decision: Literal["approved", "changes_requested", "draft"]
    note: str | None = Field(default=None, max_length=10_000)


class EvaluationCaseInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=5_000)
    case_type: Literal["sql_generation", "agent_run"] = "sql_generation"
    dialect: Literal["sqlserver", "oracle", "teradata", "bigquery", "postgres"] = "postgres"
    expected_tables: list[str] = Field(default_factory=list, max_length=50)
    required_sql_tokens: list[str] = Field(default_factory=list, max_length=50)
    expected_agents: list[str] = Field(default_factory=list, max_length=20)
    expected_tools: list[str] = Field(default_factory=list, max_length=50)
    expects_approval: bool | None = None
    golden_trace: dict[str, Any] | None = None


class EvaluationSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    cases: list[EvaluationCaseInput] = Field(min_length=1, max_length=200)


class EvaluationRunRequest(BaseModel):
    provider_id: str | None = None


class EvaluationBaselineRequest(BaseModel):
    run_id: str
    overwrite: bool = False


class RedTeamSuiteCreate(BaseModel):
    name: str = Field(default="Agent policy red-team suite", min_length=1, max_length=200)
    description: str | None = Field(
        default="Approval-boundary regression cases for governed agent execution.", max_length=5_000
    )


class LearningSuggestionReview(BaseModel):
    status: Literal["accepted", "dismissed"]
    note: str | None = Field(default=None, max_length=10_000)


class NotebookCell(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    type: Literal["markdown", "sql", "python"]
    source: str = Field(max_length=100_000)


class NotebookSave(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cells: list[NotebookCell] = Field(min_length=1, max_length=100)
    notebook_id: str | None = None


class QualityRuleCreate(BaseModel):
    asset_id: str
    name: str = Field(min_length=1, max_length=200)
    rule_type: Literal["not_null", "unique", "accepted_values", "range"]
    column_name: str = Field(min_length=1, max_length=160)
    config: dict[str, Any] = Field(default_factory=dict)
    severity: Literal["warning", "error"] = "error"


class AgentRunRequest(BaseModel):
    objective: str
    autonomy_level: int = Field(default=2, ge=0, le=3)


class AgentDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=10_000)
    autonomy_level: int = Field(default=2, ge=0, le=3)
    enabled: bool = True
    tool_names: list[str] = Field(default_factory=list, max_length=100)
    # Published QueryTool names (governed SQL tools) this agent may invoke,
    # in addition to tool_names (internal ToolDefinition registry).
    query_tool_names: list[str] = Field(default_factory=list, max_length=100)
    policy: dict[str, Any] = Field(default_factory=dict)
    instructions: str = Field(min_length=1, max_length=100_000)
    model_provider_id: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    config: dict[str, Any] = Field(default_factory=dict)


class AgentVersionCreate(BaseModel):
    instructions: str = Field(min_length=1, max_length=100_000)
    model_provider_id: str | None = None
    tool_names: list[str] = Field(default_factory=list, max_length=100)
    query_tool_names: list[str] = Field(default_factory=list, max_length=100)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    config: dict[str, Any] = Field(default_factory=dict)


class AgentDefinitionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=10_000)
    autonomy_level: int = Field(ge=0, le=3)
    enabled: bool
    policy: dict[str, Any] = Field(default_factory=dict)


class ToolDefinitionCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,119}$")
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=10_000)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    enabled: bool = True
    requires_approval: bool = False
    implementation_type: Literal["builtin", "http"] = "http"
    handler_name: str = Field(default="", max_length=160)
    endpoint: str | None = Field(default=None, max_length=1000)
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"
    parameter_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    result_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    permissions: list[str] = Field(default_factory=list, max_length=100)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=0, ge=0, le=5)
    retry_backoff_seconds: int = Field(default=1, ge=1, le=30)
    cost_class: Literal["free", "low", "medium", "high"] = "low"
    environment: str = Field(default="local", min_length=1, max_length=40)


class ToolVersionCreate(BaseModel):
    implementation_type: Literal["builtin", "http"]
    handler_name: str = Field(default="", max_length=160)
    endpoint: str | None = Field(default=None, max_length=1000)
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"
    parameter_schema: dict[str, Any]
    result_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    permissions: list[str] = Field(default_factory=list, max_length=100)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=0, ge=0, le=5)
    retry_backoff_seconds: int = Field(default=1, ge=1, le=30)
    cost_class: Literal["free", "low", "medium", "high"] = "low"
    environment: str = Field(default="local", min_length=1, max_length=40)


class ToolDefinitionUpdate(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=10_000)
    risk_level: Literal["low", "medium", "high", "critical"]
    enabled: bool
    requires_approval: bool


class ToolExecuteRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExternalClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    scopes: list[Literal["tools:list", "tools:invoke"]] = Field(
        default_factory=lambda: ["tools:list", "tools:invoke"]
    )


class ExternalClientUpdate(BaseModel):
    active: bool
    scopes: list[Literal["tools:list", "tools:invoke"]]


class QueryToolCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,119}$")
    description: str = Field(min_length=1, max_length=10_000)
    purpose: str = Field(min_length=1, max_length=10_000)
    data_source: str = Field(min_length=1, max_length=160)
    line_of_business: str = Field(min_length=1, max_length=160)
    owner: str = Field(min_length=1, max_length=160)
    tags: list[str] = Field(default_factory=list, max_length=50)
    connector_id: str | None = None
    upstream_tool_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,160}$")
    sql_template: str = Field(min_length=1, max_length=100_000)
    parameter_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False}
    )
    result_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    allowed_relations: list[str] = Field(default_factory=list, max_length=100)
    row_limit: int = Field(default=200, ge=1, le=1000)
    timeout_seconds: int = Field(default=15, ge=1, le=120)
    requires_approval: bool = False


class QueryToolInvoke(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


class QueryToolGrantCreate(BaseModel):
    external_client_id: str
    enabled: bool = True


class MCPRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class ConversationCreate(BaseModel):
    title: str = Field(default="New analysis", min_length=1, max_length=200)


class ConversationAsk(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    dialect: Literal["sqlserver", "oracle", "teradata", "bigquery", "postgres"] = "postgres"
    connector_id: str | None = None


class ConversationReportCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class PromptSave(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(min_length=1, max_length=100_000)
    template: str = Field(min_length=1, max_length=100_000)
    variables: list[str] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    prompt_id: str | None = None


class PromptRollback(BaseModel):
    version: int = Field(ge=1)


class QualityRemediationRequest(BaseModel):
    action: Literal["recheck", "purge_quarantine"]
    note: str | None = Field(default=None, max_length=10_000)


class RetentionPolicySave(BaseModel):
    resource_type: Literal["audit_events", "model_call_logs", "external_invocations", "user_feedback"]
    retention_days: int = Field(ge=1, le=3650)
    enabled: bool = True


class PipelineGenerateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=20_000)
    source_asset_ids: list[str] = Field(min_length=1, max_length=20)
    target_schema: str = Field(default="curated", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,119}$")
    target_table: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,159}$")
    code_targets: list[Literal["postgres_view", "dbt", "dataform"]] = Field(
        default_factory=lambda: list(DEFAULT_ARTIFACT_TARGETS),
        min_length=1,
        max_length=3,
    )


class PipelineUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=20_000)


class PipelinePackageSummary(BaseModel):
    target: Literal["postgres_view", "dbt", "dataform"]
    root_dir: str
    archive_name: str
    files: list[dict[str, Any]]


class PipelinePackageDeliveryConfigSave(BaseModel):
    delivery_mode: Literal["download_only", "git_prepare"] = "download_only"
    git_repository: str | None = Field(default=None, max_length=500)
    git_provider: Literal["github", "gitlab", "bitbucket", "azure_devops", "generic"] | None = None
    base_branch: str = Field(default="main", min_length=1, max_length=160)
    export_subdirectory: str | None = Field(default=None, max_length=240)
    create_branch: bool = False
    branch_strategy: Literal["none", "timestamped", "custom"] = "none"
    branch_name_template: str | None = Field(default=None, max_length=200)
    create_pr: bool = False
    pr_title_template: str | None = Field(default=None, max_length=200)
    pr_body_template: str | None = Field(default=None, max_length=5_000)


class IncidentResolveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=10_000)


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = None


class AuthProviderUpdate(BaseModel):
    enabled: bool
    issuer_url: str | None = None
    client_id: str | None = None
    scopes: str = "openid profile email"
    group_claim: str = "groups"


def as_dict(model: Any, fields: list[str]) -> dict[str, Any]:
    return {field: getattr(model, field) for field in fields}


def estimated_model_cost(input_tokens: int, output_tokens: int) -> float:
    input_rate = float(os.getenv("MODEL_INPUT_COST_PER_MILLION", "0"))
    output_rate = float(os.getenv("MODEL_OUTPUT_COST_PER_MILLION", "0"))
    return round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 8)


def project_output(project: Project, db: Session, user: User) -> dict[str, Any]:
    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == user.id,
        )
    )
    provider = db.get(ModelProvider, project.default_model_provider_id) if project.default_model_provider_id else None
    return {
        **as_dict(project, ["id", "name", "slug", "description", "environment", "active", "default_model_provider_id", "created_at", "updated_at"]),
        "membership_role": membership.role if membership else None,
        "is_current": bool(membership and membership.is_current),
        "model_provider": (
            as_dict(provider, ["id", "name", "provider_type", "default_model", "status"])
            if provider else None
        ),
    }


def session_user_output(user: User, db: Session) -> dict[str, Any]:
    membership = current_membership(db, user)
    project = db.get(Project, membership.project_id) if membership else None
    return {
        **as_dict(user, ["id", "email", "name", "role", "must_change_password"]),
        "current_project_id": project.id if project else None,
        "current_project_name": project.name if project else None,
        "effective_project_role": membership.role if membership else None,
        "permissions": sorted(project_permissions(user, membership.role if membership else None)),
    }


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "engineer": {"catalog:read", "catalog:write", "semantic:write", "query:read", "query:write", "pipeline:write", "quality:write", "registry:write", "jobs:write"},
    "analyst": {"catalog:read", "query:read", "semantic:read", "conversation:write", "feedback:write"},
    "viewer": {"catalog:read", "query:read", "semantic:read"},
    "owner": {"catalog:read", "catalog:write", "semantic:write", "query:read", "query:write", "pipeline:write", "quality:write", "registry:write", "jobs:write", "conversation:write", "feedback:write"},
    "maintainer": {"catalog:read", "catalog:write", "semantic:write", "query:read", "query:write", "pipeline:write", "quality:write", "registry:write", "jobs:write", "conversation:write", "feedback:write"},
    "member": {"catalog:read", "query:read", "semantic:read", "conversation:write", "feedback:write"},
}


def project_permissions(user: User, membership_role: str | None) -> set[str]:
    permissions = set(ROLE_PERMISSIONS.get(user.role, set()))
    permissions.update(ROLE_PERMISSIONS.get(membership_role or "", set()))
    return permissions


def require_current_project(db: Session, user: User) -> Project:
    membership = current_membership(db, user)
    project = db.get(Project, membership.project_id) if membership else None
    if project is None or not project.active:
        raise HTTPException(status_code=409, detail="Select an active project before continuing")
    return project


def require_role(user: User, allowed: set[str], detail: str) -> User:
    if user.role not in allowed:
        raise HTTPException(status_code=403, detail=detail)
    return user


def require_permission(user: User, permission: str, detail: str | None = None) -> User:
    """Authorize against the same granular permission map exposed by /auth/me."""
    if "*" not in project_permissions(user, None) and permission not in project_permissions(user, None):
        raise HTTPException(status_code=403, detail=detail or f"Permission required: {permission}")
    return user


def require_data_editor(user: User) -> User:
    return require_permission(user, "catalog:write", "Catalog write permission required")


def require_workspace_editor(user: User) -> User:
    return require_permission(user, "conversation:write", "Workspace write permission required")


def require_project_resource(resource: Any, project: Project, label: str) -> Any:
    if resource is None or getattr(resource, "project_id", None) != project.id:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return resource


def _superset_dataset(asset: DataAsset, project: Project) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "project_slug": project.slug,
        "schema_name": asset.schema_name,
        "table_name": asset.table_name,
        "columns": list(asset.columns or []),
        "source_name": asset.source_name,
        "asset_type": asset.asset_type,
        "row_count": asset.row_count,
    }


def resolve_superset_dataset(db: Session, project: Project) -> dict[str, Any]:
    inspector = inspect(engine)
    known_tables: dict[str | None, set[str]] = {}
    uses_schemas = engine.dialect.name == "postgresql"

    def table_exists(asset: DataAsset) -> bool:
        schema = None if not uses_schemas or asset.schema_name in {"", "main"} else asset.schema_name
        if schema not in known_tables:
            known_tables[schema] = set(inspector.get_table_names(schema=schema))
        return asset.table_name in known_tables[schema]

    latest_mapping = db.scalar(
        select(IngestionMapping)
        .where(
            IngestionMapping.project_id == project.id,
            IngestionMapping.latest_relation.is_not(None),
        )
        .order_by(IngestionMapping.updated_at.desc())
    )
    if latest_mapping and latest_mapping.latest_relation:
        relation = latest_mapping.latest_relation
        if "." in relation:
            schema_name, table_name = relation.split(".", 1)
        else:
            schema_name, table_name = "main", relation
        asset = db.scalar(
            select(DataAsset).where(
                DataAsset.project_id == project.id,
                DataAsset.schema_name == schema_name,
                DataAsset.table_name == table_name,
            )
        )
        if asset is not None and table_exists(asset):
            return _superset_dataset(asset, project)

    assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project.id)).all()
    candidates = [asset for asset in assets if table_exists(asset)]
    if not candidates:
        raise ValueError(
            "Load, schedule, or publish a local project dataset before opening Superset"
        )

    def asset_priority(asset: DataAsset) -> tuple[int, int, int, int, str]:
        source_rank = 0 if asset.source_name == "Local files" else 1 if asset.source_name == "DataPilot pipelines" else 2
        type_rank = 0 if asset.asset_type in {"staged_file", "view"} else 1
        schema_rank = 0 if asset.schema_name == "staging" else 1
        row_rank = -(asset.row_count or 0)
        return (
            source_rank,
            type_rank,
            schema_rank,
            row_rank,
            f"{asset.schema_name}.{asset.table_name}",
        )

    return _superset_dataset(sorted(candidates, key=asset_priority)[0], project)


def save_superset_dashboard_state(
    db: Session,
    project: Project,
    dataset: dict[str, Any],
    config: dict[str, Any],
) -> SupersetProjectDashboard:
    state = db.scalar(
        select(SupersetProjectDashboard).where(SupersetProjectDashboard.project_id == project.id)
    )
    if state is None:
        state = SupersetProjectDashboard(project_id=project.id)
        db.add(state)
    state.dashboard_id = int(config["dashboard_id"]) if config.get("dashboard_id") is not None else None
    state.dashboard_slug = str(config.get("dashboard_slug", ""))[:160]
    state.embedded_id = str(config["embedded_id"]) if config.get("embedded_id") else None
    state.dashboard_title = str(config.get("dashboard_title", ""))[:240]
    state.superset_dataset_id = (
        int(config["superset_dataset_id"]) if config.get("superset_dataset_id") is not None else None
    )
    state.dataset_schema_name = str(dataset.get("schema_name", ""))[:120]
    state.dataset_table_name = str(dataset.get("table_name", ""))[:160]
    state.dataset_column_count = len(list(dataset.get("columns") or []))
    chart_ids = config.get("chart_ids") or []
    state.chart_ids = [int(chart_id) for chart_id in chart_ids if isinstance(chart_id, int) or str(chart_id).isdigit()]
    state.access_mode = str(config.get("access_mode", "dashboard_scope"))[:64]
    state.rls_column = str(config["rls_column"])[:160] if config.get("rls_column") else None
    db.flush()
    return state


def save_superset_query_dashboard_state(
    db: Session,
    project: Project,
    artifact: Artifact,
    artifact_version: int,
    sql: str,
    columns: list[dict[str, Any]],
    config: dict[str, Any],
    published_by: str,
) -> SupersetQueryDashboard:
    """Persist the dedicated dashboard provisioned for one published SQL/notebook query.

    Keyed by (project_id, artifact_id) so re-publishing a later version of the
    same saved artifact updates its existing dedicated dashboard instead of
    creating a duplicate — mirroring how save_superset_dashboard_state treats
    the project's primary dashboard as a stable, upsertable identity.
    """
    state = db.scalar(
        select(SupersetQueryDashboard).where(
            SupersetQueryDashboard.project_id == project.id,
            SupersetQueryDashboard.artifact_id == artifact.id,
        )
    )
    if state is None:
        state = SupersetQueryDashboard(project_id=project.id, artifact_id=artifact.id, published_by=published_by)
        db.add(state)
    state.artifact_version = artifact_version
    state.query_name = str(config.get("dataset_relation", "")).split(".")[-1][:160]
    state.sql = sql[:20000]
    state.columns = columns
    state.dashboard_id = int(config["dashboard_id"]) if config.get("dashboard_id") is not None else None
    state.dashboard_slug = str(config.get("dashboard_slug", ""))[:160]
    state.embedded_id = str(config["embedded_id"]) if config.get("embedded_id") else None
    state.dashboard_title = str(config.get("dashboard_title", ""))[:240]
    state.superset_dataset_id = (
        int(config["superset_dataset_id"]) if config.get("superset_dataset_id") is not None else None
    )
    chart_ids = config.get("chart_ids") or []
    state.chart_ids = [int(chart_id) for chart_id in chart_ids if isinstance(chart_id, int) or str(chart_id).isdigit()]
    state.access_mode = str(config.get("access_mode", "dashboard_scope"))[:64]
    state.rls_column = str(config["rls_column"])[:160] if config.get("rls_column") else None
    state.published_by = published_by
    db.flush()
    return state


def connector_output(connector: Connector, include_secret: bool = False) -> dict[str, Any]:
    output = as_dict(
        connector,
        [
            "id",
            "name",
            "connector_type", "connection_mode",
            "description",
            "host",
            "database",
            "mcp_server_url",
            "status",
            "read_only",
            "metadata_summary",
            "last_scanned_at",
        ],
    )
    if include_secret:
        output["secret_reference"] = connector.secret_reference
    return output


def _validate_connector_contract(payload: ConnectorCreate | ConnectorUpdate) -> None:
    if payload.connection_mode == "mcp":
        if payload.connector_type == "local_files":
            raise HTTPException(status_code=400, detail="Local files do not support MCP connection mode")
        try:
            endpoint = httpx.URL(payload.mcp_server_url or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail="A valid MCP server URL is required") from exc
        if endpoint.scheme not in {"http", "https"} or not endpoint.host:
            raise HTTPException(status_code=400, detail="MCP connection mode requires an http(s) server URL")
        if endpoint.userinfo:
            raise HTTPException(status_code=400, detail="MCP credentials must use an env: secret reference, not the URL")
    elif payload.mcp_server_url:
        raise HTTPException(status_code=400, detail="mcp_server_url is only valid in MCP connection mode")


def dataset_category(asset: DataAsset, connector: Connector | None) -> str:
    if asset.asset_type == "staged_file":
        return "Imported file"
    if asset.asset_type == "view":
        return "Curated view"
    if connector:
        return "External source"
    if any(tag.lower() in {"pii_candidate", "sensitive"} for tag in asset.tags):
        return "Sensitive catalog"
    return "Catalog"


def audit(
    db: Session,
    actor: User | None,
    event_type: str,
    entity_type: str,
    entity_id: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    membership = current_membership(db, actor) if actor else None
    project_id = membership.project_id if membership else None
    audit_details = details or {}
    db.add(
        AuditEvent(
            project_id=project_id,
            actor_id=actor.id if actor else None,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            details=audit_details,
        )
    )
    # Every durable audit action is also exported so external governance has
    # the same activity coverage as the local audit trail.
    record_audit_event(
        event_type,
        entity_type,
        entity_id,
        project_id=project_id,
        user_id=actor.id if actor else None,
        details=audit_details,
    )


def save_internal_artifact_version(
    db: Session,
    user: User,
    name: str,
    artifact_type: str,
    content: str,
    metadata: dict[str, Any],
    artifact_id: str | None = None,
) -> tuple[Artifact, ArtifactVersion]:
    project = require_current_project(db, user)
    artifact = db.get(Artifact, artifact_id) if artifact_id else None
    if artifact is not None:
        require_project_resource(artifact, project, "Artifact")
    if artifact is None:
        artifact = Artifact(
            project_id=project.id,
            name=name,
            artifact_type=artifact_type,
            created_by=user.id,
        )
        db.add(artifact)
        db.flush()
    else:
        artifact.name = name
        artifact.updated_at = datetime.now(timezone.utc)
    current_version = db.scalar(
        select(func.max(ArtifactVersion.version)).where(ArtifactVersion.artifact_id == artifact.id)
    ) or 0
    version = ArtifactVersion(
        artifact_id=artifact.id,
        version=current_version + 1,
        content=content,
        artifact_metadata=metadata,
        created_by=user.id,
    )
    db.add(version)
    db.flush()
    return artifact, version


SECURITY_CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("prompt_injection", "Prompt Injection", ("prompt injection", "jailbreak", "instruction override")),
    ("pii_exposure", "PII Exposure", ("pii", "social security", "ssn", "credit card", "personal data")),
    ("toxic_content", "Toxic Content", ("toxic", "abusive", "hate speech", "harassment")),
]
SECURITY_CATEGORY_LABELS = {key: label for key, label, _ in SECURITY_CATEGORIES}
SECURITY_SEVERITIES = ("critical", "high", "medium", "low")


def _security_bucket_label(value: datetime) -> str:
    return f"{value.strftime('%b')} {value.day}"


def _security_text(incident: Incident) -> str:
    return " ".join(
        part
        for part in (
            incident.title,
            incident.root_cause,
            json.dumps(incident.evidence, separators=(",", ":"), default=str),
            " ".join(incident.remediation or []),
        )
        if part
    ).lower()


def _security_category_from_incident(incident: Incident) -> str | None:
    text = _security_text(incident)
    for key, _, keywords in SECURITY_CATEGORIES:
        if any(keyword in text for keyword in keywords):
            return key
    return None


def _security_score(incidents: list[Incident]) -> int:
    deductions = {"critical": 20, "high": 12, "medium": 7, "low": 3}
    score = 100
    for incident in incidents:
        score -= deductions.get((incident.severity or "").lower(), 5)
    return max(0, min(100, score))


def _security_posture(score: int) -> str:
    if score >= 90:
        return "Good"
    if score >= 75:
        return "Monitor"
    return "At Risk"


def external_extraction_output(extraction: ExternalExtraction, db: Session) -> dict[str, Any]:
    connector = db.get(Connector, extraction.connector_id)
    asset = db.get(DataAsset, extraction.source_asset_id)
    return {
        **as_dict(
            extraction,
            [
                "id", "name", "connector_id", "source_asset_id", "target_table", "load_mode",
                "key_columns", "watermark_column", "last_watermark", "batch_limit", "status",
                "latest_relation", "run_count", "artifact_id", "created_at", "updated_at",
            ],
        ),
        "connector_name": connector.name if connector else "missing connector",
        "source_relation": f"{asset.schema_name}.{asset.table_name}" if asset else "missing asset",
    }


def external_extraction_columns(asset: DataAsset) -> list[dict[str, Any]]:
    return [
        {
            "source_name": str(column.get("name")),
            "target_name": safe_identifier(str(column.get("name")), "column"),
            "target_type": _json_schema_type(column),
            "nullable": bool(column.get("nullable", True)),
        }
        for column in asset.columns
        if column.get("name")
    ]


def schedule_output(schedule: IngestionSchedule, db: Session) -> dict[str, Any]:
    mapping = db.get(IngestionMapping, schedule.mapping_id)
    item = db.get(IngestedFile, mapping.file_id) if mapping else None
    return {
        **as_dict(
            schedule,
            [
                "id", "name", "mapping_id", "cron", "timezone", "load_mode",
                "key_columns", "watermark_column", "last_watermark", "enabled",
                "next_run_at", "last_run_at", "created_at",
            ],
        ),
        "mapping_name": mapping.name if mapping else "missing mapping",
        "filename": item.filename if item else "missing file",
        "target_table": mapping.target_table if mapping else None,
    }


# generated_sql / generated_catalog_sql moved to sql_generation.py so the
# internal tool registry's sql.generate builtin handler (tool_runtime.py) can
# import them without a circular import (tool_runtime.py must never import
# from main.py). Imported here under the same names so every router's
# existing `from ..main import generated_catalog_sql, generated_sql` keeps
# working unchanged.
from .sql_generation import generated_catalog_sql, generated_sql


def connector_dialect(connector: Connector | None, requested_dialect: str) -> str:
    """Use the registered system type as the source of truth for analysis SQL."""
    if connector is None:
        return requested_dialect
    return {
        "postgres": "postgres",
        "sql_server": "sqlserver",
        "local_files": "postgres",
        "oracle": "oracle",
        "teradata": "teradata",
        "bigquery": "bigquery",
    }.get(connector.connector_type, requested_dialect)


def analysis_source_output(connector: Connector | None, dialect: str) -> dict[str, Any]:
    if connector is None:
        return {
            "id": None,
            "name": "DataPilot local workspace",
            "database": "PostgreSQL staging",
            "connector_type": "local_files",
            "dialect": dialect,
        }
    return {
        "id": connector.id,
        "name": connector.name,
        "database": connector.database or connector.host or connector.name,
        "connector_type": connector.connector_type,
        "dialect": dialect,
    }


def refresh_conversation_summary(conversation: Conversation, messages: list[ConversationMessage]) -> str:
    """Maintain a deterministic long-horizon memory without storing a hidden model transcript."""
    meaningful = [message for message in messages if message.role in {"user", "assistant"}]
    if len(meaningful) <= 12:
        conversation.summary = ""
        return ""
    highlights = [
        f"{message.role}: {message.content.replace(chr(10), ' ').strip()[:360]}"
        for message in meaningful[-12:]
    ]
    conversation.summary = "Earlier conversation summary:\n" + "\n".join(highlights)
    return conversation.summary


def compact_conversation_context(messages: list[ConversationMessage], summary: str = "") -> list[dict[str, str]]:
    """Persist full messages, but send only bounded recent context plus durable summary to the model."""
    context = ([{"role": "system", "content": summary[:4_000]}] if summary else [])
    context.extend([
        {"role": message.role, "content": message.content[:2_000]}
        for message in messages[-16:]
        if message.role in {"user", "assistant"}
    ])
    return context


def _sql_cache_key(
    project_id: str,
    connector_id: str | None,
    dialect: str,
    normalized_question: str,
    context_hash: str,
    grounding_signature: str,
) -> str:
    payload = {
        "project_id": project_id,
        "connector_id": connector_id,
        "dialect": dialect,
        "question": normalized_question,
        "context_hash": context_hash,
        "grounding_signature": grounding_signature,
    }
    return hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _cached_sql_response(
    db: Session,
    *,
    project_id: str,
    cache_key: str,
) -> dict[str, Any] | None:
    cached = db.scalar(
        select(SQLQueryCache).where(
            SQLQueryCache.project_id == project_id,
            SQLQueryCache.cache_key == cache_key,
        )
    )
    if cached is None or not cached.result:
        return None
    cached.hit_count += 1
    cached.last_used_at = datetime.now(timezone.utc)
    payload = json.loads(json.dumps(cached.result, default=str))
    provider = payload.get("provider") or {}
    payload["provider"] = {
        **provider,
        "mode": "cache_reuse",
        "latency_ms": 0,
    }
    payload["cache"] = {
        "hit": True,
        "cache_key": cached.cache_key,
        "normalized_question": cached.normalized_question,
        "created_at": cached.created_at.isoformat(),
        "updated_at": cached.updated_at.isoformat() if cached.updated_at else cached.created_at.isoformat(),
        "last_used_at": cached.last_used_at.isoformat(),
        "hit_count": cached.hit_count,
    }
    return payload


def _store_sql_query_cache(
    db: Session,
    *,
    project_id: str,
    connector_id: str | None,
    dialect: str,
    normalized_question: str,
    context_hash: str,
    grounding_signature: str,
    cache_key: str,
    result: dict[str, Any],
    created_by: str | None,
) -> None:
    payload = json.loads(json.dumps(result, default=str))
    payload["cache"] = {
        "hit": False,
        "cache_key": cache_key,
        "normalized_question": normalized_question,
    }
    cached = db.scalar(
        select(SQLQueryCache).where(
            SQLQueryCache.project_id == project_id,
            SQLQueryCache.cache_key == cache_key,
        )
    )
    if cached is None:
        db.add(
            SQLQueryCache(
                project_id=project_id,
                connector_id=connector_id,
                dialect=dialect,
                normalized_question=normalized_question,
                context_signature=context_hash,
                grounding_signature=grounding_signature,
                cache_key=cache_key,
                result=payload,
                hit_count=0,
                created_by=created_by,
            )
        )
        return
    cached.connector_id = connector_id
    cached.dialect = dialect
    cached.normalized_question = normalized_question
    cached.context_signature = context_hash
    cached.grounding_signature = grounding_signature
    cached.result = payload
    cached.updated_at = datetime.now(timezone.utc)


def conversational_analysis_answer(
    provider: ModelProvider,
    question: str,
    analysis: dict[str, Any],
    prior_message_count: int,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> str:
    execution = analysis.get("execution") or {}
    source = analysis.get("source") or {}
    if execution.get("error"):
        summary = f"I prepared a safe {analysis['dialect']} query, but its preview could not run: {execution['error']}"
    elif execution:
        summary = f"I found {execution.get('row_count', 0)} row{'s' if execution.get('row_count', 0) != 1 else ''} in the preview."
    else:
        summary = f"I prepared a safe {analysis['dialect']} query for the selected source."
    memory_note = " I used the earlier discussion in this topic to interpret this follow-up." if prior_message_count else ""
    deterministic = (
        f"{summary}{memory_note} "
        f"The governed SQL, validation checks, and source context for {source.get('name', 'the selected source')} are attached below."
    )
    if os.getenv("CONVERSATION_MODEL_SUMMARY_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return deterministic
    if provider.provider_type == "local_mock":
        return f"{summary}{memory_note} The SQL and validation details are attached below; ask a follow-up in this same topic and I will retain the context."
    try:
        response = generate_text(
            provider,
            "You are a concise data analyst in a continuing chat. Explain the result naturally in 2-4 sentences. Respect the provided evidence, do not invent findings, and do not include SQL or markdown tables.",
            json.dumps({"question": question, "analysis": analysis, "prior_message_count": prior_message_count}, default=str)[:18_000],
            900,
            governance_feature="conversation_summary",
            governance_business_id=project_id,
            governance_session_id=session_id,
            governance_user_id=user_id,
        )
        return response.content.strip()[:4_000] or deterministic
    except Exception:
        return deterministic


def _extract_sql(value: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.*?)(?:```|$)", value, re.IGNORECASE | re.DOTALL)
    candidate = (fenced.group(1) if fenced else value).strip()
    start = re.search(r"\b(select|with)\b", candidate, re.IGNORECASE)
    if start:
        candidate = candidate[start.start():]
    return candidate.split("```")[0].strip()


def _safe_read_only_sql(sql: str) -> bool:
    normalized = sql.strip()
    destructive = bool(re.search(r"\b(drop|delete|truncate|alter|update|insert|merge|grant|revoke)\b", normalized, re.I))
    multiple_statements = ";" in normalized.rstrip().rstrip(";")
    balanced = normalized.count("(") == normalized.count(")") and normalized.replace("''", "").count("'") % 2 == 0
    complete = not re.search(r"(?:\b(and|or|where|from|join|on|as|in)|[,.(=])\s*;?$", normalized, re.I)
    return bool(re.match(r"^\s*(select|with)\b", normalized, re.I)) and not destructive and not multiple_statements and balanced and complete


def _column_sql_context_entry(column: dict[str, Any]) -> str:
    business_name = column.get("business_name")
    business_suffix = f" ({business_name})" if business_name else ""
    required_suffix = "" if column.get("nullable", True) else ", required"
    return f"{column.get('name', '')}{business_suffix} ({column.get('type', 'unknown')}{required_suffix})"


def _catalog_sql_context(assets: list[DataAsset]) -> str:
    """Format catalog metadata so SQL generation can respect actual data types."""
    entries: list[str] = []
    for asset in assets[:40]:
        columns = ", ".join(
            _column_sql_context_entry(column) for column in asset.columns if column.get("name")
        )
        entries.append(
            f"- {asset.schema_name}.{asset.table_name}: {columns or 'No column metadata'}. {asset.description or ''}"
        )
    return "\n".join(entries)


def _local_execution_error(sql: str) -> dict[str, Any] | None:
    try:
        return execute_read_only(engine, sql, 500)
    except Exception as exc:
        return {
            "error": str(exc),
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "limit": 500,
        }


AGENT_APPROVAL_KEYWORDS = (
    "schedule",
    "write",
    "create table",
    "publish",
    "deploy",
    "execute",
    "delete",
    "drop",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "export",
    "send",
    "email",
)


def agent_run_requires_approval(objective: str) -> bool:
    return any(word in objective.lower() for word in AGENT_APPROVAL_KEYWORDS)


def initial_agent_plan(requires_approval: bool) -> list[dict[str, str]]:
    return [
        {"agent": "Planner", "action": "Decompose objective and set limits", "status": "waiting"},
        {"agent": "Metadata", "action": "Ground against catalog and semantic terms", "status": "waiting"},
        {"agent": "SQL Analyst", "action": "Draft dialect-aware query", "status": "waiting"},
        {"agent": "Quality", "action": "Validate assumptions and evidence", "status": "waiting"},
        {
            "agent": "Policy",
            "action": "Request human approval" if requires_approval else "Confirm read-only execution",
            "status": "waiting" if requires_approval else "complete",
        },
    ]


def pipeline_output(pipeline: PipelineDefinition, db: Session) -> dict[str, Any]:
    version = db.scalar(select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version))
    definition = version.definition if version else {}
    return {
        **as_dict(pipeline, ["id", "project_id", "name", "objective", "status", "current_version", "artifact_id", "created_by", "created_at", "updated_at"]),
        "definition": definition,
        "generated_code": version.generated_code if version else "",
        "generated_artifacts": definition.get("artifacts", []),
    }


def _get_project_pipeline_with_version(
    pipeline_id: str,
    *,
    user: User,
    db: Session,
) -> tuple[Project, PipelineDefinition, PipelineVersion]:
    project = require_current_project(db, user)
    pipeline = db.get(PipelineDefinition, pipeline_id)
    if pipeline is None or pipeline.project_id != project.id or pipeline.status == "deleted":
        raise HTTPException(status_code=404, detail="Pipeline not found")
    version = db.scalar(
        select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline.id,
            PipelineVersion.version == pipeline.current_version,
        )
    )
    if version is None:
        raise HTTPException(status_code=409, detail="Pipeline has no versioned definition")
    return project, pipeline, version


def _build_pipeline_package_or_404(
    pipeline: PipelineDefinition,
    version: PipelineVersion,
    package_target: Literal["postgres_view", "dbt", "dataform"],
) -> dict[str, Any]:
    definition = version.definition or {}
    target = definition.get("target", {})
    sources = definition.get("sources", [])
    artifacts = definition.get("artifacts", [])
    if not artifacts:
        raise HTTPException(status_code=404, detail="Pipeline package artifacts were not generated")
    delivery_config = _delivery_config_for_target(definition, package_target)
    try:
        package = build_exported_package(
            pipeline_name=pipeline.name,
            pipeline_version=pipeline.current_version,
            package_target=package_target,
            target_schema=str(target.get("schema", "curated")),
            target_table=str(target.get("table", "pipeline_output")),
            source_count=len(sources),
            artifacts=artifacts,
            delivery_config=delivery_config,
        )
    except PipelineGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return {
        **package.as_dict(),
        "delivery_config": delivery_config,
        "delivery_plan": _build_delivery_plan(
            pipeline_name=pipeline.name,
            pipeline_version=pipeline.current_version,
            package_target=package_target,
            delivery_config=delivery_config,
        ),
    }


def _default_delivery_config(
    package_target: Literal["postgres_view", "dbt", "dataform"],
) -> dict[str, Any]:
    branch_template = (
        f"datapilot/{package_target}/{{pipeline_slug}}/v{{pipeline_version}}"
        if package_target != "postgres_view"
        else f"datapilot/sql/{{pipeline_slug}}/v{{pipeline_version}}"
    )
    pr_title = "Export {pipeline_name} ({package_target}) v{pipeline_version}"
    return {
        "delivery_mode": "download_only",
        "git_repository": None,
        "git_provider": None,
        "base_branch": "main",
        "export_subdirectory": None,
        "create_branch": False,
        "branch_strategy": "none",
        "branch_name_template": branch_template,
        "create_pr": False,
        "pr_title_template": pr_title,
        "pr_body_template": (
            "Generated by DataPilot.\n\n"
            "- Pipeline: {pipeline_name}\n"
            "- Target: {package_target}\n"
            "- Version: {pipeline_version}\n"
        ),
    }


def _normalize_delivery_config(
    package_target: Literal["postgres_view", "dbt", "dataform"],
    payload: dict[str, Any] | PipelinePackageDeliveryConfigSave | None,
) -> dict[str, Any]:
    config = _default_delivery_config(package_target)
    if payload:
        values = payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)
        for key, value in values.items():
            if key in config:
                config[key] = value
    for key in ("git_repository", "export_subdirectory", "branch_name_template", "pr_title_template", "pr_body_template"):
        if isinstance(config.get(key), str):
            config[key] = config[key].strip() or None
    if config["delivery_mode"] == "download_only":
        config["create_branch"] = False
        config["create_pr"] = False
        config["branch_strategy"] = "none"
    if config["delivery_mode"] == "git_prepare":
        if not config.get("git_repository"):
            raise HTTPException(status_code=422, detail="A git_repository is required when delivery_mode is git_prepare")
        if config["create_pr"] and not config["create_branch"]:
            raise HTTPException(status_code=422, detail="create_pr requires create_branch to be enabled")
        if config["create_branch"] and config["branch_strategy"] == "none":
            config["branch_strategy"] = "timestamped"
        if config["branch_strategy"] == "custom" and not config.get("branch_name_template"):
            raise HTTPException(status_code=422, detail="branch_name_template is required when branch_strategy is custom")
    return config


def _delivery_config_for_target(
    definition: dict[str, Any],
    package_target: Literal["postgres_view", "dbt", "dataform"],
) -> dict[str, Any]:
    package_delivery = definition.get("package_delivery", {})
    stored = package_delivery.get(package_target)
    return _normalize_delivery_config(package_target, stored)


def _build_delivery_plan(
    *,
    pipeline_name: str,
    pipeline_version: int,
    package_target: Literal["postgres_view", "dbt", "dataform"],
    delivery_config: dict[str, Any],
) -> list[dict[str, str]]:
    mode = str(delivery_config.get("delivery_mode", "download_only"))
    plan = [
        {
            "step": "Export package archive",
            "status": "configured",
            "detail": f"Package target {package_target} will be exported as a downloadable bundle.",
        }
    ]
    if mode == "download_only":
        plan.append(
            {
                "step": "Manual repository handoff",
                "status": "optional",
                "detail": "No Git operations are configured; the exported bundle can be reviewed or pushed manually.",
            }
        )
        return plan
    repository = str(delivery_config.get("git_repository") or "")
    plan.append(
        {
            "step": "Prepare repository destination",
            "status": "configured",
            "detail": f"Repository metadata is stored for future export into {repository}.",
        }
    )
    if delivery_config.get("create_branch"):
        strategy = str(delivery_config.get("branch_strategy", "timestamped"))
        template = str(delivery_config.get("branch_name_template") or "")
        plan.append(
            {
                "step": "Prepare branch name",
                "status": "configured",
                "detail": f"Branch creation is enabled with {strategy} strategy using template `{template}`.",
            }
        )
    if delivery_config.get("create_pr"):
        title_template = str(delivery_config.get("pr_title_template") or "")
        plan.append(
            {
                "step": "Prepare PR metadata",
                "status": "configured",
                "detail": f"PR creation is enabled with title template `{title_template}`.",
            }
        )
    else:
        plan.append(
            {
                "step": "PR creation",
                "status": "optional",
                "detail": "PR metadata is not enabled for this package configuration.",
            }
        )
    plan.append(
        {
            "step": "External Git integration",
            "status": "not_executed",
            "detail": f"DataPilot stores this plan only; no branch or PR is created as of August 2, 2026.",
        }
    )
    return plan


def quality_rule_output(rule: QualityRule, db: Session) -> dict[str, Any]:
    asset = db.get(DataAsset, rule.asset_id)
    latest = db.scalar(
        select(QualityRun)
        .where(QualityRun.rule_id == rule.id)
        .order_by(QualityRun.created_at.desc())
        .limit(1)
    )
    return {
        **as_dict(
            rule,
            ["id", "asset_id", "name", "rule_type", "column_name", "config", "severity", "enabled", "artifact_id", "created_at"],
        ),
        "dataset": f"{asset.schema_name}.{asset.table_name}" if asset else "missing asset",
        "latest_run": (
            as_dict(latest, ["id", "status", "checked_rows", "failed_rows", "pass_rate", "quarantine_relation", "created_at"])
            if latest
            else None
        ),
    }


def create_quality_rule_record(
    db: Session,
    user: User,
    asset: DataAsset,
    name: str,
    rule_type: str,
    column_name: str,
    config: dict[str, Any],
    severity: str,
) -> QualityRule:
    rule = QualityRule(
        project_id=asset.project_id,
        asset_id=asset.id,
        name=name,
        rule_type=rule_type,
        column_name=column_name,
        config=config,
        severity=severity,
        created_by=user.id,
    )
    db.add(rule)
    db.flush()
    definition = {
        "dataset": f"{asset.schema_name}.{asset.table_name}",
        "name": name,
        "rule_type": rule_type,
        "column_name": column_name,
        "config": config,
        "severity": severity,
    }
    artifact, _ = save_internal_artifact_version(
        db,
        user,
        name,
        "quality_rule",
        json.dumps(definition, indent=2),
        {"quality_rule_id": rule.id, "asset_id": asset.id},
    )
    rule.artifact_id = artifact.id
    return rule


def semantic_join_policy_output(policy: SemanticJoinPolicy) -> dict[str, Any]:
    return as_dict(
        policy,
        [
            "id", "project_id", "left_asset_id", "right_asset_id", "left_column", "right_column",
            "join_type", "description", "status", "created_at", "updated_at",
        ],
    )


def validate_semantic_join_policy(
    db: Session, project_id: str, payload: SemanticJoinPolicyCreate
) -> None:
    if payload.left_asset_id == payload.right_asset_id:
        raise HTTPException(status_code=422, detail="A join policy must reference two different datasets")
    assets = [db.get(DataAsset, payload.left_asset_id), db.get(DataAsset, payload.right_asset_id)]
    if any(asset is None or asset.project_id != project_id for asset in assets):
        raise HTTPException(status_code=404, detail="A join-policy dataset was not found in this project")
    left, right = assets
    assert left is not None and right is not None
    left_columns = set(column_names_for_asset(left))
    right_columns = set(column_names_for_asset(right))
    if payload.left_column not in left_columns:
        raise HTTPException(status_code=422, detail=f"Column {payload.left_column} is not present on {left.schema_name}.{left.table_name}")
    if payload.right_column not in right_columns:
        raise HTTPException(status_code=422, detail=f"Column {payload.right_column} is not present on {right.schema_name}.{right.table_name}")


def column_names_for_asset(asset: DataAsset) -> list[str]:
    return [str(column.get("name", "")).strip() for column in asset.columns if str(column.get("name", "")).strip()]


def require_semantic_maintainer(db: Session, user: User, project_id: str) -> None:
    membership = current_membership(db, user)
    if membership is None or membership.project_id != project_id or (user.role not in {"admin", "engineer"} and membership.role not in {"owner", "maintainer"}):
        raise HTTPException(status_code=403, detail="Project maintainer access required")
    require_permission(user, "semantic:write", "Semantic write permission required")


def run_agent_evaluation_case(
    db: Session,
    project: Project,
    user: User,
    evaluation_run_id: str,
    case: dict[str, Any],
) -> dict[str, Any]:
    """Replay an agent objective without allowing an approval-gated action to run."""
    objective = str(case["question"])
    requires_approval = agent_run_requires_approval(objective)
    job = Job(
        project_id=project.id,
        title=f"Evaluation: {case['name']}"[:200],
        job_type="agent_evaluation",
        status="SIMULATED_APPROVAL_REQUIRED" if requires_approval else "PLANNING",
        progress=100 if requires_approval else 5,
        plan=initial_agent_plan(requires_approval),
        evidence=[
            {"type": "evaluation", "label": evaluation_run_id},
            {"type": "policy", "label": "Approval simulated" if requires_approval else "Read-only local replay"},
        ],
        outputs=[],
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    if requires_approval:
        job.outputs = [
            {
                "type": "policy_simulation",
                "agent": "Policy",
                "title": "Approval boundary reached",
                "summary": "The objective was not executed because it requires human approval.",
                "data": {"requires_approval": True},
                "at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        db.commit()
    else:
        # The local runner uses its own session, so commit this evaluation job first.
        db.commit()
        run_agent_plan_locally(job.id, objective)
        db.expire_all()
        job = db.get(Job, job.id)
        if job is None:
            raise ValueError("Agent evaluation job disappeared during replay")

    observed_plan = [
        {"agent": str(step["agent"]), "action": re.sub(r"\s+", " ", str(step.get("action", "")).strip())}
        for step in job.plan
        if step.get("agent")
    ]
    observed_agents = [step["agent"] for step in observed_plan]
    observed_tools = sorted(
        {
            str(output.get("tool"))
            for output in job.outputs
            if output.get("type") in {"tool_result", "tool_error"} and output.get("tool")
        }
    )
    checks = [
        {"kind": "agent", "value": agent, "passed": agent in observed_agents}
        for agent in case.get("expected_agents", [])
    ] + [
        {"kind": "tool", "value": tool, "passed": tool in observed_tools}
        for tool in case.get("expected_tools", [])
    ]
    if case.get("expects_approval") is not None:
        checks.append(
            {
                "kind": "approval",
                "value": bool(case["expects_approval"]),
                "passed": requires_approval is bool(case["expects_approval"]),
            }
        )
    golden_trace = case.get("golden_trace") or {}
    actual_trace = {
        "agents": observed_agents,
        "plan_actions": [step["action"] for step in observed_plan],
        "tools": observed_tools,
        "requires_approval": requires_approval,
    }
    if golden_trace:
        if "agents" in golden_trace:
            checks.append(
                {
                    "kind": "golden_agents",
                    "value": golden_trace["agents"],
                    "passed": list(golden_trace["agents"]) == actual_trace["agents"],
                }
            )
        if "plan_actions" in golden_trace:
            expected_actions = [re.sub(r"\s+", " ", str(action).strip()) for action in golden_trace["plan_actions"]]
            checks.append(
                {
                    "kind": "golden_plan_actions",
                    "value": expected_actions,
                    "passed": expected_actions == actual_trace["plan_actions"],
                }
            )
        if "tools" in golden_trace:
            checks.append(
                {
                    "kind": "golden_tools",
                    "value": sorted(str(tool) for tool in golden_trace["tools"]),
                    "passed": sorted(str(tool) for tool in golden_trace["tools"]) == actual_trace["tools"],
                }
            )
        if "requires_approval" in golden_trace:
            checks.append(
                {
                    "kind": "golden_policy",
                    "value": bool(golden_trace["requires_approval"]),
                    "passed": bool(golden_trace["requires_approval"]) is requires_approval,
                }
            )
    score = 100.0 if not checks else 100.0 * sum(check["passed"] for check in checks) / len(checks)
    return {
        "name": case["name"],
        "case_type": "agent_run",
        "status": "passed" if score == 100 else "failed",
        "score": round(score, 2),
        "checks": checks,
        "job_id": job.id,
        "simulation": requires_approval,
        "observed_agents": observed_agents,
        "observed_tools": observed_tools,
        "observed_plan": observed_plan,
        "golden_trace": actual_trace,
        "job_status": job.status,
    }


def external_client_output(client: ExternalClient) -> dict[str, Any]:
    return as_dict(client, ["id", "name", "client_id", "active", "scopes", "default_project_id", "created_by", "created_at"])


def query_tool_output(tool: QueryTool) -> dict[str, Any]:
    return as_dict(
        tool,
        [
            "id", "project_id", "name", "description", "purpose", "data_source",
            "line_of_business", "owner", "tags", "connector_id", "upstream_tool_name", "sql_template",
            "parameter_schema", "result_schema", "allowed_relations", "row_limit",
            "timeout_seconds", "requires_approval", "status", "version", "created_by",
            "created_at", "updated_at",
        ],
    )


def _identifier_quote(value: str, dialect: str) -> str:
    identifier = safe_identifier(value, "value")
    if dialect == "bigquery":
        return f"`{identifier}`"
    if dialect == "sqlserver":
        return f"[{identifier}]"
    return f'"{identifier}"' if dialect in {"postgres", "oracle"} else identifier


def _asset_relation_sql(asset: DataAsset, connector: Connector | None) -> tuple[str, str]:
    dialect = connector_dialect(connector, "postgres")
    schema_name = safe_identifier(asset.schema_name, "public")
    table_name = safe_identifier(asset.table_name, "dataset")
    relation = f"{schema_name}.{table_name}"
    if dialect == "bigquery":
        return relation, f"`{relation}`"
    if dialect == "sqlserver":
        return relation, f"[{schema_name}].[{table_name}]"
    if dialect in {"postgres", "oracle"}:
        return relation, f'"{schema_name}"."{table_name}"'
    return relation, relation


def _json_schema_type(column: dict[str, Any]) -> str:
    column_type = str(column.get("type", "")).lower()
    if any(token in column_type for token in ("int", "serial")):
        return "integer"
    if any(token in column_type for token in ("decimal", "numeric", "float", "double", "real")):
        return "number"
    if any(token in column_type for token in ("bool", "bit")):
        return "boolean"
    return "string"


def _external_client_from_header(
    authorization: str | None,
    db: Session,
    required_scope: str,
) -> ExternalClient:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="External client bearer token required")
    token = authorization[7:].strip()
    if "." not in token:
        raise HTTPException(status_code=401, detail="Invalid external client token")
    client_id, secret = token.split(".", 1)
    client = db.scalar(select(ExternalClient).where(ExternalClient.client_id == client_id))
    if client is None or not client.active or not verify_password(secret, client.secret_hash):
        raise HTTPException(status_code=401, detail="Invalid external client token")
    if required_scope not in client.scopes:
        raise HTTPException(status_code=403, detail=f"Missing scope: {required_scope}")
    return client


def _validate_query_tool_contract(payload: QueryToolCreate, db: Session, project: Project) -> None:
    schema = payload.parameter_schema
    if schema.get("type") != "object" or not isinstance(schema.get("properties", {}), dict):
        raise HTTPException(status_code=400, detail="Parameter schema must be a JSON Schema object")
    placeholders = set(re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", payload.sql_template))
    properties = set(schema.get("properties", {}))
    if not placeholders.issubset(properties):
        raise HTTPException(status_code=400, detail="Every SQL parameter must be declared in parameter_schema")
    probe = re.sub(r"(?<!:):[A-Za-z_][A-Za-z0-9_]*", "NULL", payload.sql_template)
    if not _safe_read_only_sql(probe):
        raise HTTPException(status_code=400, detail="Query tools require one complete read-only SELECT statement")
    normalized_sql = re.sub(r'["`\[\]\s]', "", payload.sql_template.lower())
    normalized_relations = [re.sub(r'["`\[\]\s]', "", relation.lower()) for relation in payload.allowed_relations]
    if any(relation not in normalized_sql for relation in normalized_relations):
        raise HTTPException(status_code=400, detail="Every allowed relation must be referenced by the SQL template")
    if payload.connector_id:
        connector = require_project_resource(db.get(Connector, payload.connector_id), project, "Connector")
        if connector.connection_mode == "mcp" and not payload.upstream_tool_name:
            raise HTTPException(status_code=400, detail="MCP-backed query tools require upstream_tool_name")
        if connector.connection_mode != "mcp" and payload.upstream_tool_name:
            raise HTTPException(status_code=400, detail="upstream_tool_name is only valid for an MCP-backed connector")
    elif payload.upstream_tool_name:
        raise HTTPException(status_code=400, detail="upstream_tool_name requires an MCP-backed connector")


def _registry_metadata(tool: QueryTool) -> dict[str, Any]:
    return {
        "purpose": tool.purpose,
        "data_source": tool.data_source,
        "line_of_business": tool.line_of_business,
        "owner": tool.owner,
        "tags": tool.tags or [],
        "version": tool.version,
    }


def _external_query_tool_output(tool: QueryTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        **_registry_metadata(tool),
        "input_schema": tool.parameter_schema,
        "result_schema": tool.result_schema,
        "annotations": {
            "read_only": True,
            "destructive": False,
            "row_limit": tool.row_limit,
            "timeout_seconds": tool.timeout_seconds,
        },
    }


def _filter_registry_tools(
    tools: list[QueryTool],
    q: str = "",
    data_source: str = "",
    line_of_business: str = "",
    tag: str = "",
) -> list[QueryTool]:
    query = q.strip().lower()
    source = data_source.strip().lower()
    lob = line_of_business.strip().lower()
    wanted_tag = tag.strip().lower()
    filtered: list[QueryTool] = []
    for tool in tools:
        searchable = " ".join(
            [tool.name, tool.description, tool.purpose, tool.data_source, tool.line_of_business, tool.owner]
            + list(tool.tags or [])
        ).lower()
        if query and query not in searchable:
            continue
        if source and source not in tool.data_source.lower():
            continue
        if lob and lob not in tool.line_of_business.lower():
            continue
        if wanted_tag and wanted_tag not in {item.lower() for item in tool.tags or []}:
            continue
        filtered.append(tool)
    return filtered


def _validate_tool_parameters(schema: dict[str, Any], parameters: dict[str, Any]) -> None:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    missing = sorted(required - set(parameters))
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required parameters: {', '.join(missing)}")
    if schema.get("additionalProperties", True) is False:
        unknown = sorted(set(parameters) - set(properties))
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown parameters: {', '.join(unknown)}")
    expected_types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for name, value in parameters.items():
        declaration = properties.get(name, {})
        expected = expected_types.get(declaration.get("type"))
        if expected and (not isinstance(value, expected) or declaration.get("type") in {"integer", "number"} and isinstance(value, bool)):
            raise HTTPException(status_code=400, detail=f"Parameter {name} has the wrong type")
        if "enum" in declaration and value not in declaration["enum"]:
            raise HTTPException(status_code=400, detail=f"Parameter {name} is not an allowed value")


def _granted_query_tools(db: Session, client: ExternalClient) -> list[QueryTool]:
    return db.scalars(
        select(QueryTool)
        .join(QueryToolGrant, QueryToolGrant.query_tool_id == QueryTool.id)
        .where(
            QueryTool.project_id == client.default_project_id,
            QueryTool.status == "published",
            QueryToolGrant.external_client_id == client.id,
            QueryToolGrant.enabled.is_(True),
        )
        .order_by(QueryTool.name)
    ).all()


EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE = int(os.getenv("EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE", "60"))


def _invoke_external_query_tool(
    db: Session,
    client: ExternalClient,
    tool: QueryTool,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    rate = check_rate_limit(f"external_client:{client.id}", EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE, 60)
    if not rate.allowed:
        audit(
            db, None, "external_query_tool.rate_limited", "external_client", client.id,
            {"limit_per_minute": rate.limit, "query_tool": tool.name, "project_id": tool.project_id},
        )
        db.commit()
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {rate.limit} requests/minute for this client",
            headers={"Retry-After": str(rate.retry_after_seconds)},
        )
    grant = db.scalar(
        select(QueryToolGrant).where(
            QueryToolGrant.query_tool_id == tool.id,
            QueryToolGrant.external_client_id == client.id,
            QueryToolGrant.enabled.is_(True),
        )
    )
    if tool.project_id != client.default_project_id or tool.status != "published" or grant is None:
        raise HTTPException(status_code=404, detail="Published query tool not found")
    if tool.requires_approval:
        raise HTTPException(status_code=409, detail="This tool requires an interactive portal approval")
    _validate_tool_parameters(tool.parameter_schema, parameters)
    invocation = ExternalInvocation(
        project_id=tool.project_id,
        external_client_id=client.id,
        query_tool_id=tool.id,
        parameters=parameters,
    )
    db.add(invocation)
    db.flush()
    record_governance_event(
        "external_query_tool",
        tool.name,
        "started",
        project_id=tool.project_id,
        user_id=client.client_id,
        session_id=invocation.id,
        feature="external_query_tool",
        external_client_id=client.id,
        query_tool_id=tool.id,
        connector_id=tool.connector_id or "",
        row_limit=tool.row_limit,
    )
    started = time.perf_counter()
    try:
        if tool.connector_id:
            connector = db.get(Connector, tool.connector_id)
            if connector is None or connector.project_id != tool.project_id:
                raise ConnectorRuntimeError("The configured connector is unavailable")
            result = execute_connector_query(
                connector, tool.sql_template, parameters, tool.row_limit, tool.timeout_seconds,
                upstream_tool_name=tool.upstream_tool_name,
                user_id=client.client_id,
                session_id=invocation.id,
                feature="external_query_tool",
            )
        else:
            result = execute_parameterized_read_only(
                engine, tool.sql_template, parameters, tool.row_limit, tool.timeout_seconds
            )
        serializable = json.loads(json.dumps(result, default=str))
        invocation.status = "succeeded"
        invocation.duration_ms = round((time.perf_counter() - started) * 1000)
        invocation.result_metadata = {
            "columns": serializable["columns"],
            "row_count": serializable["row_count"],
            "truncated": serializable["truncated"],
        }
        db.commit()
        record_governance_event(
            "external_query_tool",
            tool.name,
            "succeeded",
            project_id=tool.project_id,
            user_id=client.client_id,
            session_id=invocation.id,
            feature="external_query_tool",
            external_client_id=client.id,
            query_tool_id=tool.id,
            duration_ms=invocation.duration_ms,
            row_count=serializable["row_count"],
            truncated=serializable["truncated"],
        )
        return {"invocation_id": invocation.id, "tool": tool.name, **serializable}
    except HTTPException as exc:
        invocation.status = "failed"
        invocation.duration_ms = round((time.perf_counter() - started) * 1000)
        invocation.error = str(exc.detail)[:2000]
        db.commit()
        record_governance_event(
            "external_query_tool",
            tool.name,
            "failed",
            project_id=tool.project_id,
            user_id=client.client_id,
            session_id=invocation.id,
            feature="external_query_tool",
            external_client_id=client.id,
            query_tool_id=tool.id,
            duration_ms=invocation.duration_ms,
            error_type=type(exc).__name__,
        )
        raise
    except ConnectionLimitExceeded as exc:
        invocation.status = "failed"
        invocation.duration_ms = round((time.perf_counter() - started) * 1000)
        invocation.error = str(exc)[:2000]
        db.commit()
        record_governance_event(
            "external_query_tool",
            tool.name,
            "failed",
            project_id=tool.project_id,
            user_id=client.client_id,
            session_id=invocation.id,
            feature="external_query_tool",
            external_client_id=client.id,
            query_tool_id=tool.id,
            duration_ms=invocation.duration_ms,
            error_type=type(exc).__name__,
        )
        # 503, not the generic 422 below: this is a transient capacity signal
        # (too many simultaneous connections to the source system right now),
        # not a malformed request -- a well-behaved client should retry.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        invocation.status = "failed"
        invocation.duration_ms = round((time.perf_counter() - started) * 1000)
        invocation.error = str(exc)[:2000]
        db.commit()
        record_governance_event(
            "external_query_tool",
            tool.name,
            "failed",
            project_id=tool.project_id,
            user_id=client.client_id,
            session_id=invocation.id,
            feature="external_query_tool",
            external_client_id=client.id,
            query_tool_id=tool.id,
            duration_ms=invocation.duration_ms,
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=422, detail=f"Query tool execution failed: {exc}") from exc


def query_tool_usage_summary(db: Session, tool: QueryTool) -> dict[str, Any]:
    invocations = db.scalars(
        select(ExternalInvocation)
        .where(ExternalInvocation.project_id == tool.project_id, ExternalInvocation.query_tool_id == tool.id)
        .order_by(ExternalInvocation.created_at.desc())
    ).all()
    succeeded = [item for item in invocations if item.status == "succeeded"]
    failed = [item for item in invocations if item.status == "failed"]
    durations = sorted(item.duration_ms for item in invocations if item.duration_ms is not None)
    midpoint = len(durations) // 2
    median_latency_ms = (
        round(sum(durations[midpoint - 1 : midpoint + 1]) / len(durations[midpoint - 1 : midpoint + 1]), 2)
        if durations
        else None
    )
    parameter_key_counts: dict[str, int] = {}
    client_counts: dict[str, int] = {}
    client_ids = {item.external_client_id for item in invocations}
    clients = {
        client.id: client.name
        for client in db.scalars(select(ExternalClient).where(ExternalClient.id.in_(client_ids))).all()
    } if client_ids else {}
    for invocation in invocations:
        client_name = clients.get(invocation.external_client_id, "Unknown client")
        client_counts[client_name] = client_counts.get(client_name, 0) + 1
        for key in (invocation.parameters or {}).keys():
            parameter_key_counts[str(key)] = parameter_key_counts.get(str(key), 0) + 1
    return {
        "invocation_count": len(invocations),
        "success_count": len(succeeded),
        "failure_count": len(failed),
        "success_rate": round(100 * len(succeeded) / len(invocations), 2) if invocations else None,
        "median_latency_ms": median_latency_ms,
        "rows_returned": sum(int((item.result_metadata or {}).get("row_count", 0) or 0) for item in succeeded),
        "last_invoked_at": invocations[0].created_at if invocations else None,
        "client_usage": [
            {"client": name, "invocations": count}
            for name, count in sorted(client_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "parameter_key_usage": [
            {"parameter": key, "invocations": count}
            for key, count in sorted(parameter_key_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "recent_errors": [
            {"at": item.created_at, "error": (item.error or "Execution failed")[:500]}
            for item in failed[:5]
        ],
    }


def conversation_output(conversation: Conversation, db: Session) -> dict[str, Any]:
    messages = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at)
    ).all()
    return {
        **as_dict(conversation, ["id", "project_id", "title", "summary", "created_by", "created_at", "updated_at"]),
        "message_count": len(messages),
        "last_message": messages[-1].content[:240] if messages else None,
    }


def _chart_from_result(question: str, execution: dict[str, Any] | None) -> dict[str, Any]:
    if not execution or execution.get("error") or not execution.get("rows"):
        return {"type": "table", "title": question[:120], "data": []}
    rows = json.loads(json.dumps(execution["rows"][:100], default=str))
    columns = execution.get("columns", [])
    numeric = next(
        (
            column for column in columns
            if any(isinstance(row.get(column), (int, float)) and not isinstance(row.get(column), bool) for row in rows)
        ),
        None,
    )
    category = next((column for column in columns if column != numeric), None)
    if numeric and category:
        lowered = category.lower()
        chart_type = "line" if any(token in lowered for token in ("date", "day", "week", "month", "year", "time")) else "bar"
        return {"type": chart_type, "title": question[:120], "x": category, "y": numeric, "data": rows}
    return {"type": "table", "title": question[:120], "data": rows}


# --- Domain routers (see apps/api/app/routers/) ---
from .routers import (
    admin,
    agents,
    analytics,
    approvals,
    artifacts,
    auth,
    connectors,
    conversations,
    evaluations,
    files,
    governance,
    jobs,
    model_providers,
    notebooks,
    pipelines,
    projects,
    prompts,
    quality,
    query_tools,
    retention_policies,
    semantic,
    sql,
    system,
    tools,
    workspace,
)

for _router_module in (
    admin,
    agents,
    analytics,
    approvals,
    artifacts,
    auth,
    connectors,
    conversations,
    evaluations,
    files,
    governance,
    jobs,
    model_providers,
    notebooks,
    pipelines,
    projects,
    prompts,
    quality,
    query_tools,
    retention_policies,
    semantic,
    sql,
    system,
    tools,
    workspace,
):
    app.include_router(_router_module.router)
