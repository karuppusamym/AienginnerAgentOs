from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="analyst")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthProvider(Base):
    __tablename__ = "auth_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_type: Mapped[str] = mapped_column(String(32), default="pingfederate_oidc")
    name: Mapped[str] = mapped_column(String(100), default="Company PingFederate")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    issuer_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scopes: Mapped[str] = mapped_column(String(255), default="openid profile email")
    group_claim: Mapped[str] = mapped_column(String(100), default="groups")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ModelProvider(Base):
    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[str] = mapped_column(String(40))
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_model: Mapped[str] = mapped_column(String(160))
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    secret_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="not_tested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelCallLog(Base):
    __tablename__ = "model_call_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("model_providers.id"))
    model: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(String(80), default="provider_test")
    status: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str] = mapped_column(String(40), default="local")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    default_model_provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_providers.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupersetProjectDashboard(Base):
    __tablename__ = "superset_project_dashboards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), unique=True, index=True)
    dashboard_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dashboard_slug: Mapped[str] = mapped_column(String(160), default="")
    embedded_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    dashboard_title: Mapped[str] = mapped_column(String(240), default="")
    superset_dataset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_schema_name: Mapped[str] = mapped_column(String(120), default="")
    dataset_table_name: Mapped[str] = mapped_column(String(160), default="")
    dataset_column_count: Mapped[int] = mapped_column(Integer, default=0)
    chart_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    access_mode: Mapped[str] = mapped_column(String(64), default="dashboard_scope")
    rls_column: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SupersetQueryDashboard(Base):
    """A dedicated, per-artifact Superset dashboard for a published SQL/notebook query.

    This is intentionally a separate table from ``SupersetProjectDashboard``
    (which tracks exactly one dashboard per project, used for the project's
    primary staged/mapped dataset). Each approved query publication gets its
    own dashboard identity so that publishing a governed SQL or notebook
    result never overwrites the project's main analytics dashboard — the two
    previously collided because both were being provisioned under the same
    Superset dashboard slug, derived only from the project slug.
    """

    __tablename__ = "superset_query_dashboards"
    __table_args__ = (UniqueConstraint("project_id", "artifact_id", name="uq_superset_query_dashboard_artifact"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    artifact_version: Mapped[int] = mapped_column(Integer, default=0)
    query_name: Mapped[str] = mapped_column(String(160), default="")
    sql: Mapped[str] = mapped_column(Text, default="")
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    dashboard_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dashboard_slug: Mapped[str] = mapped_column(String(160), default="")
    embedded_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    dashboard_title: Mapped[str] = mapped_column(String(240), default="")
    superset_dataset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chart_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    access_mode: Mapped[str] = mapped_column(String(64), default="dashboard_scope")
    rls_column: Mapped[str | None] = mapped_column(String(160), nullable=True)
    published_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SemanticMetric(Base):
    __tablename__ = "semantic_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("data_assets.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula: Mapped[str] = mapped_column(Text)
    grain: Mapped[str] = mapped_column(String(255))
    owner: Mapped[str] = mapped_column(String(160))
    dimensions: Mapped[list[str]] = mapped_column(JSON, default=list)
    synonyms: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SemanticJoinPolicy(Base):
    """A governed relationship between two catalog assets.

    Pipelines only use approved policies automatically.  Draft policies are
    intentionally visible to reviewers but cannot change generated SQL.
    """

    __tablename__ = "semantic_join_policies"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "left_asset_id", "right_asset_id", "left_column", "right_column",
            name="uq_semantic_join_policy",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    left_asset_id: Mapped[str] = mapped_column(ForeignKey("data_assets.id"), index=True)
    right_asset_id: Mapped[str] = mapped_column(ForeignKey("data_assets.id"), index=True)
    left_column: Mapped[str] = mapped_column(String(160))
    right_column: Mapped[str] = mapped_column(String(160))
    join_type: Mapped[str] = mapped_column(String(24), default="inner")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    purpose: Mapped[str] = mapped_column(Text)
    autonomy_level: Mapped[int] = mapped_column(Integer, default=2)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tool_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Names of published QueryTool records (governed SQL tools with business
    # metadata: purpose/data_source/line_of_business/owner) this agent may
    # invoke during a bounded run, resolved against the run's project.
    # Distinct from tool_names, which references the internal ToolDefinition
    # registry (built-in handlers / allowlisted HTTP).
    query_tool_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ToolDefinition(Base):
    __tablename__ = "tool_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    category: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(24), default="low")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_definitions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str] = mapped_column(Text)
    model_provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_providers.id"), nullable=True
    )
    tool_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    query_tool_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    evaluation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolVersion(Base):
    __tablename__ = "tool_versions"
    __table_args__ = (UniqueConstraint("tool_id", "version", name="uq_tool_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_definitions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    implementation_type: Mapped[str] = mapped_column(String(32), default="builtin")
    handler_name: Mapped[str] = mapped_column(String(160))
    endpoint: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    http_method: Mapped[str] = mapped_column(String(16), default="POST")
    parameter_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, default=1)
    cost_class: Mapped[str] = mapped_column(String(24), default="low")
    environment: Mapped[str] = mapped_column(String(40), default="local")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_definitions.id"), index=True)
    tool_version: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineDefinition(Base):
    __tablename__ = "pipeline_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PipelineVersion(Base):
    __tablename__ = "pipeline_versions"
    __table_args__ = (UniqueConstraint("pipeline_id", "version", name="uq_pipeline_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipeline_definitions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generated_code: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LineageEdge(Base):
    __tablename__ = "lineage_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    pipeline_id: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_definitions.id"), nullable=True
    )
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey("data_assets.id"), nullable=True)
    target_asset_id: Mapped[str | None] = mapped_column(ForeignKey("data_assets.id"), nullable=True)
    source_relation: Mapped[str] = mapped_column(String(320))
    target_relation: Mapped[str] = mapped_column(String(320))
    transformation: Mapped[str] = mapped_column(Text)
    column_mapping: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    severity: Mapped[str] = mapped_column(String(24), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="open")
    root_cause: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    remediation: Mapped[list[str]] = mapped_column(JSON, default=list)
    retry_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserFeedback(Base):
    __tablename__ = "user_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    context_type: Mapped[str] = mapped_column(String(80))
    context_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rating: Mapped[str] = mapped_column(String(24))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningSuggestion(Base):
    """Human-reviewed improvement candidate derived from governed feedback."""

    __tablename__ = "learning_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    feedback_id: Mapped[str] = mapped_column(
        ForeignKey("user_feedback.id"), unique=True, index=True
    )
    category: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="open")
    title: Mapped[str] = mapped_column(String(220))
    rationale: Mapped[str] = mapped_column(Text)
    proposed_change: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str] = mapped_column(String(16), default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    connector_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    connection_mode: Mapped[str] = mapped_column(String(24), default="direct")
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    database: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mcp_server_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="not_tested")
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GlossaryDocument(Base):
    """A business-context document (SOP, glossary, definitions) uploaded to
    ground SQL generation and conversations. Not tabular data -- see
    IngestedFile for that. Text is extracted at upload time (PDF via pypdf,
    or taken directly for .txt/.md), truncated to a bounded size, stored
    here, and indexed into the vector store so grounding_context() can
    retrieve relevant passages the same way it retrieves catalog matches.
    """

    __tablename__ = "glossary_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    source_filename: Mapped[str | None] = mapped_column(String(320), nullable=True)
    content_type: Mapped[str] = mapped_column(String(16), default="text")
    extracted_text: Mapped[str] = mapped_column(Text)
    character_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataAsset(Base):
    __tablename__ = "data_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    connector_id: Mapped[str | None] = mapped_column(
        ForeignKey("connectors.id"), nullable=True
    )
    source_name: Mapped[str] = mapped_column(String(120))
    schema_name: Mapped[str] = mapped_column(String(120))
    table_name: Mapped[str] = mapped_column(String(160))
    asset_type: Mapped[str] = mapped_column(String(32), default="table")
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sensitivity: Mapped[str] = mapped_column(String(32), default="unclassified")
    freshness_sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_status: Mapped[str] = mapped_column(String(32), default="scanned")


class IngestedFile(Base):
    __tablename__ = "ingested_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="profiled")
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionMapping(Base):
    __tablename__ = "ingestion_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("ingested_files.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_schema: Mapped[str] = mapped_column(String(120), default="staging")
    target_table: Mapped[str] = mapped_column(String(160))
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    latest_relation: Mapped[str | None] = mapped_column(String(320), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ExternalExtraction(Base):
    __tablename__ = "external_extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id"), index=True)
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("data_assets.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_table: Mapped[str] = mapped_column(String(160))
    load_mode: Mapped[str] = mapped_column(String(24), default="append")
    key_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    watermark_column: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_watermark: Mapped[str | None] = mapped_column(String(500), nullable=True)
    batch_limit: Mapped[int] = mapped_column(Integer, default=5_000)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    latest_relation: Mapped[str | None] = mapped_column(String(320), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class QualityRule(Base):
    __tablename__ = "quality_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("data_assets.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    rule_type: Mapped[str] = mapped_column(String(40))
    column_name: Mapped[str] = mapped_column(String(160))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(24), default="error")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityRun(Base):
    __tablename__ = "quality_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("quality_rules.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    checked_rows: Mapped[int] = mapped_column(Integer, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float] = mapped_column(Float, default=100.0)
    sample_failures: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    quarantine_relation: Mapped[str | None] = mapped_column(String(320), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    job_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    logs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    outputs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    title: Mapped[str] = mapped_column(String(200))
    action_type: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[str] = mapped_column(String(24), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    artifact_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionSchedule(Base):
    __tablename__ = "ingestion_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    mapping_id: Mapped[str] = mapped_column(ForeignKey("ingestion_mappings.id"), index=True)
    cron: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    load_mode: Mapped[str] = mapped_column(String(24), default="append")
    key_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    watermark_column: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_watermark: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ArtifactComment(Base):
    __tablename__ = "artifact_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationSet(Base):
    __tablename__ = "evaluation_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    evaluation_set_id: Mapped[str] = mapped_column(ForeignKey("evaluation_sets.id"), index=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("model_providers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalClient(Base):
    __tablename__ = "external_clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    client_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QueryTool(Base):
    __tablename__ = "query_tools"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_query_tool"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text, default="")
    data_source: Mapped[str] = mapped_column(String(160), default="")
    line_of_business: Mapped[str] = mapped_column(String(160), default="")
    owner: Mapped[str] = mapped_column(String(160), default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    connector_id: Mapped[str | None] = mapped_column(ForeignKey("connectors.id"), nullable=True)
    upstream_tool_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sql_template: Mapped[str] = mapped_column(Text)
    parameter_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    allowed_relations: Mapped[list[str]] = mapped_column(JSON, default=list)
    row_limit: Mapped[int] = mapped_column(Integer, default=200)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class QueryToolGrant(Base):
    __tablename__ = "query_tool_grants"
    __table_args__ = (UniqueConstraint("query_tool_id", "external_client_id", name="uq_query_tool_client"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    query_tool_id: Mapped[str] = mapped_column(ForeignKey("query_tools.id"), index=True)
    external_client_id: Mapped[str] = mapped_column(ForeignKey("external_clients.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalInvocation(Base):
    __tablename__ = "external_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    external_client_id: Mapped[str] = mapped_column(ForeignKey("external_clients.id"), index=True)
    query_tool_id: Mapped[str] = mapped_column(ForeignKey("query_tools.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
    structured: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SQLQueryCache(Base):
    __tablename__ = "sql_query_cache"
    __table_args__ = (UniqueConstraint("project_id", "cache_key", name="uq_sql_query_cache_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    connector_id: Mapped[str | None] = mapped_column(ForeignKey("connectors.id"), nullable=True, index=True)
    dialect: Mapped[str] = mapped_column(String(32))
    normalized_question: Mapped[str] = mapped_column(Text)
    context_signature: Mapped[str] = mapped_column(String(40), index=True)
    grounding_signature: Mapped[str] = mapped_column(String(40), index=True)
    cache_key: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QueryRun(Base):
    __tablename__ = "query_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    connector_id: Mapped[str | None] = mapped_column(ForeignKey("connectors.id"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    sql: Mapped[str] = mapped_column(Text)
    dialect: Mapped[str] = mapped_column(String(32))
    provider: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    grounding: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="generated")
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    __table_args__ = (UniqueConstraint("project_id", "resource_type", name="uq_project_retention_resource"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    retention_days: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SchemaDriftEvent(Base):
    __tablename__ = "schema_drift_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("data_assets.id"), index=True)
    relation: Mapped[str] = mapped_column(String(320))
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="detected")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelRoute(Base):
    """Per-purpose model choice. project_id NULL = platform-wide default for that purpose."""

    __tablename__ = "model_routes"
    __table_args__ = (UniqueConstraint("project_id", "purpose", name="uq_model_route_purpose"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str] = mapped_column(ForeignKey("model_providers.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RouteDecision(Base):
    """One routing decision for a chat turn, kept for audit and offline policy evaluation."""

    __tablename__ = "route_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    backend: Mapped[str] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(80))
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    risk: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
