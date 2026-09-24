"""API response serializers (``*_output``) shared by several routers."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Connector,
    Conversation,
    ConversationMessage,
    DataAsset,
    ExternalClient,
    ExternalExtraction,
    IngestedFile,
    IngestionMapping,
    IngestionSchedule,
    ModelProvider,
    PipelineDefinition,
    PipelineVersion,
    Project,
    ProjectMembership,
    QualityRule,
    QualityRun,
    QueryTool,
    SemanticJoinPolicy,
    User,
)
from ..provider_selection import current_membership
from ..roles import project_permissions
from .common import as_dict


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


def pipeline_output(pipeline: PipelineDefinition, db: Session) -> dict[str, Any]:
    version = db.scalar(select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version))
    definition = version.definition if version else {}
    return {
        **as_dict(pipeline, ["id", "project_id", "name", "objective", "status", "current_version", "artifact_id", "created_by", "created_at", "updated_at"]),
        "definition": definition,
        "generated_code": version.generated_code if version else "",
        "generated_artifacts": definition.get("artifacts", []),
    }


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


def semantic_join_policy_output(policy: SemanticJoinPolicy) -> dict[str, Any]:
    return as_dict(
        policy,
        [
            "id", "project_id", "left_asset_id", "right_asset_id", "left_column", "right_column",
            "join_type", "description", "status", "created_at", "updated_at",
        ],
    )


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
