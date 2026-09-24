"""Request/response schemas shared by the API routers (moved out of main.py)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .pipeline_codegen import DEFAULT_ARTIFACT_TARGETS


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
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=320)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=500)


class ProviderCreate(BaseModel):
    name: str
    provider_type: Literal[
        "company_gateway", "gemini", "openai", "claude", "openai_compatible", "openrouter", "jev", "local_mock"
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
    metadata_status: Literal["scanned", "reviewed", "certified", "deprecated", "ai_suggested"] | None = None
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
    dialect: Literal["postgres", "sqlserver", "oracle", "teradata", "bigquery"] = "postgres"
    connector_id: str | None = None
    limit: int = Field(default=500, ge=1, le=1000)


class SQLExplainRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    dialect: Literal["postgres", "sqlserver", "oracle", "teradata", "bigquery"] = "postgres"
    connector_id: str | None = None


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
    # Lead agent chosen by the decision router (or the user); the planner must include it.
    agent_id: str | None = Field(default=None, max_length=36)


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
    # Token lifetime; omitted = the token does not expire.
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ExternalClientRotate(BaseModel):
    # New lifetime for the rotated token; omitted = keep the client's current expiry.
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


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
    # Invocations of this tool by this client per UTC day; omitted/null = unlimited.
    daily_quota: int | None = Field(default=None, ge=1, le=1_000_000)


class MCPRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class ConversationCreate(BaseModel):
    title: str = Field(default="New analysis", min_length=1, max_length=200)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


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
