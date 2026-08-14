"""Auto-extracted approvals routes from the former monolithic main.py.

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


@router.get("/approvals")
def list_approvals(
    status: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    statement = select(Approval).where(Approval.project_id == project.id).order_by(Approval.created_at.desc())
    if status:
        statement = statement.where(Approval.status == status.lower())
    approvals = db.scalars(statement).all()
    return [
        as_dict(
            approval,
            [
                "id",
                "job_id",
                "title",
                "action_type",
                "risk_level",
                "status",
                "evidence",
                "decision_note",
                "created_at",
                "decided_at",
            ],
        )
        for approval in approvals
    ]

@router.post("/approvals/{approval_id}/decision")
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permission(user, db, "jobs:write", "Approval action requires jobs:write permission")
    project = require_current_project(db, user)
    approval = require_project_resource(db.get(Approval, approval_id), project, "Approval")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval has already been decided")
    approval.status = payload.decision
    approval.decision_note = payload.note
    approval.decided_by = user.id
    approval.decided_at = datetime.now(timezone.utc)
    job = db.get(Job, approval.job_id)
    if job:
        job.status = "PLANNING" if payload.decision == "approved" else "CANCELLED"
        job.progress = 10 if payload.decision == "approved" else 100
    schedule = None
    if approval.action_type == "enable_ingestion_schedule":
        schedule_id = str(approval.evidence.get("schedule_id", ""))
        schedule = db.get(IngestionSchedule, schedule_id)
        if schedule and payload.decision == "approved":
            schedule.enabled = True
            schedule.next_run_at = next_run_at(schedule.cron)
        if job:
            job.status = "SUCCEEDED" if payload.decision == "approved" else "CANCELLED"
            job.progress = 100
            job.plan = [{**step, "status": "complete" if payload.decision == "approved" else "cancelled"} for step in job.plan]
    if approval.action_type == "deploy_pipeline":
        pipeline = db.get(PipelineDefinition, str(approval.evidence.get("pipeline_id", "")))
        if pipeline and payload.decision == "approved":
            version = db.scalar(select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version))
            if version is None:
                raise HTTPException(status_code=409, detail="Pipeline version not found")
            definition = version.definition
            target = definition["target"]
            source_assets = [db.get(DataAsset, source["asset_id"]) for source in definition.get("sources", [])]
            if not source_assets or any(
                asset is None
                or asset.project_id != project.id
                or (asset.connector_id is not None and (db.get(Connector, asset.connector_id) is None or db.get(Connector, asset.connector_id).host != "mock-sqlserver"))
                for asset in source_assets
            ):
                raise HTTPException(status_code=409, detail="Pipeline sources are no longer available as local governed datasets")
            target_schema = safe_identifier(target["schema"], "curated")
            target_table = safe_identifier(target["table"], "pipeline_output")
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{target_schema}"'))
                connection.execute(text(version.generated_code))
                row_count = int(connection.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."{target_table}"')).scalar() or 0)
            target_asset = db.scalar(select(DataAsset).where(DataAsset.project_id == project.id, DataAsset.schema_name == target_schema, DataAsset.table_name == target_table))
            if target_asset is None:
                target_asset = DataAsset(project_id=project.id, source_name="DataPilot pipelines", schema_name=target_schema, table_name=target_table, asset_type="view", row_count=row_count, columns=definition.get("output_columns", []), tags=["pipeline-output", "governed"], description=f"Published by {pipeline.name}")
                db.add(target_asset)
                db.flush()
            else:
                target_asset.row_count = row_count
                target_asset.columns = definition.get("output_columns", target_asset.columns)
            for edge in db.scalars(select(LineageEdge).where(LineageEdge.pipeline_id == pipeline.id)).all():
                edge.target_asset_id = target_asset.id
            pipeline.status = "active"
            if job:
                job.status = "SUCCEEDED"
                job.progress = 100
                job.plan = [{**step, "status": "complete"} for step in job.plan]
                job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Published local view {target_schema}.{target_table}"}]
        elif pipeline:
            pipeline.status = "draft"
    if approval.action_type == "tool_execution":
        execution = db.get(ToolExecution, str(approval.evidence.get("tool_execution_id", "")))
        if execution and payload.decision == "approved":
            tool = db.get(ToolDefinition, execution.tool_id)
            version = db.scalar(select(ToolVersion).where(ToolVersion.tool_id == execution.tool_id, ToolVersion.version == execution.tool_version))
            if tool is None or version is None:
                raise HTTPException(status_code=409, detail="Tool definition changed before approval")
            try:
                result, attempts, duration_ms = execute_tool(
                    db,
                    version.implementation_type,
                    version.handler_name,
                    version.endpoint,
                    version.http_method,
                    version.parameter_schema,
                    execution.parameters,
                    execution.project_id,
                    version.timeout_seconds,
                    version.max_retries,
                    version.retry_backoff_seconds,
                    user_id=user.id,
                    session_id=job.id if job else execution.id,
                )
                execution.status = "SUCCEEDED"
                execution.result = result
                execution.attempt_count = attempts
                execution.duration_ms = duration_ms
                if job:
                    job.status = "SUCCEEDED"
                    job.progress = 100
                    job.plan = [{**step, "status": "complete"} for step in job.plan]
            except ToolRuntimeError as exc:
                execution.status = "FAILED"
                execution.error = str(exc)[:5000]
                if job:
                    job.status = "FAILED"
                    job.progress = 100
                    job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "error", "message": execution.error}]
            execution.completed_at = datetime.now(timezone.utc)
        elif execution:
            execution.status = "CANCELLED"
            execution.completed_at = datetime.now(timezone.utc)
    if approval.action_type == "quality_remediation" and payload.decision == "approved":
        source_run = db.get(QualityRun, str(approval.evidence.get("quality_run_id", "")))
        if source_run is None or source_run.project_id != project.id:
            raise HTTPException(status_code=409, detail="Quality run no longer exists")
        action = str(approval.evidence.get("action", ""))
        if action == "purge_quarantine":
            relation = source_run.quarantine_relation or ""
            parts = relation.split(".", 1)
            if len(parts) != 2 or parts[0] != "quarantine" or not parts[1].startswith("q_"):
                raise HTTPException(status_code=409, detail="Only generated quarantine relations can be purged")
            table_name = safe_identifier(parts[1], "quarantine_rows")
            with engine.begin() as connection:
                connection.execute(text(f'DROP TABLE IF EXISTS "quarantine"."{table_name}"'))
            source_run.quarantine_relation = None
        elif action == "recheck":
            rule = db.get(QualityRule, source_run.rule_id)
            asset = db.get(DataAsset, rule.asset_id) if rule else None
            if rule is None or asset is None or rule.project_id != project.id:
                raise HTTPException(status_code=409, detail="Quality rule or dataset no longer exists")
            rerun = QualityRun(project_id=project.id, rule_id=rule.id, status="running", created_by=user.id)
            db.add(rerun)
            db.flush()
            result = execute_quality_rule(engine, asset.schema_name, asset.table_name, rule.name, rule.rule_type, rule.column_name, rule.config, rerun.id)
            for key, value in result.items():
                setattr(rerun, key, value)
            if job:
                job.evidence = [*job.evidence, {"type": "quality_run", "label": rerun.id}]
        if job:
            job.status = "SUCCEEDED"
            job.progress = 100
            job.plan = [{**step, "status": "complete"} for step in job.plan]
    if approval.action_type == "apply_retention" and payload.decision == "approved":
        policy = db.get(RetentionPolicy, str(approval.evidence.get("policy_id", "")))
        if policy is None or policy.project_id != project.id:
            raise HTTPException(status_code=409, detail="Retention policy no longer exists")
        cutoff = datetime.now(timezone.utc) - timedelta(days=policy.retention_days)
        model = {"audit_events": AuditEvent, "model_call_logs": ModelCallLog, "external_invocations": ExternalInvocation, "user_feedback": UserFeedback}[policy.resource_type]
        deleted_count = db.execute(delete(model).where(model.project_id == project.id, model.created_at < cutoff)).rowcount or 0
        if job:
            job.status = "SUCCEEDED"
            job.progress = 100
            job.evidence = [*job.evidence, {"type": "deleted_records", "label": str(deleted_count)}]
            job.plan = [{**step, "status": "complete"} for step in job.plan]
    if approval.action_type == "publish_superset_query" and payload.decision == "approved":
        artifact_id = str(approval.evidence.get("artifact_id", ""))
        artifact_version = int(approval.evidence.get("artifact_version", 0) or 0)
        artifact = db.get(Artifact, artifact_id)
        version = db.scalar(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact_id,
                ArtifactVersion.version == artifact_version,
            )
        )
        if artifact is None or artifact.project_id != project.id or version is None:
            raise HTTPException(status_code=409, detail="The approved source artifact version is no longer available")
        source_type = str(approval.evidence.get("source_type", ""))
        if source_type == "sql_artifact" and artifact.artifact_type == "sql":
            sql = version.content
        elif source_type == "notebook_sql_cell" and artifact.artifact_type == "notebook":
            cells = json.loads(version.content).get("cells", [])
            sql = next((str(cell.get("source", "")) for cell in reversed(cells) if cell.get("type") == "sql" and str(cell.get("source", "")).strip()), "")
        else:
            raise HTTPException(status_code=409, detail="The approved source type no longer matches its artifact")
        if not sql or not _safe_read_only_sql(sql):
            raise HTTPException(status_code=409, detail="The approved source is no longer a safe read-only query")
        try:
            preview = execute_read_only(engine, sql, 1)
            query_name = safe_identifier(
                f"dp_query_{artifact.id[:8]}_v{artifact_version}", "datapilot_query"
            )
            columns = [{"name": column, "type": "text"} for column in preview["columns"]]
            dataset = {
                "project_id": project.id,
                "project_slug": project.slug,
                "schema_name": "staging",
                "table_name": query_name,
                "columns": columns,
                "source_name": "DataPilot governed SQL",
                "asset_type": "virtual_query",
                "row_count": None,
                "sql": sql.strip().rstrip(";"),
            }
            # Dedicated dashboard identity per source artifact — publishing a
            # query must never reuse the project's primary dashboard slug
            # (both previously collided under `datapilot-project-{slug}`,
            # silently overwriting whatever the project dashboard showed).
            dashboard_key = f"query-{artifact.id}"
            config = main.get_embed_configuration(project.name, project.slug, dataset, dashboard_key)
            state = main.save_superset_query_dashboard_state(
                db, project, artifact, artifact_version, sql.strip().rstrip(";"), columns, config, user.id
            )
        except (RuntimeError, httpx.HTTPError) as exc:
            raise HTTPException(status_code=503, detail=f"Superset publication failed: {exc}") from exc
        if job:
            job.status = "SUCCEEDED"
            job.progress = 100
            job.evidence = [
                *job.evidence,
                {"type": "superset_dashboard", "label": str(config.get("dashboard_slug", ""))},
                {"type": "superset_dataset", "label": str(state.superset_dataset_id or "")},
            ]
            job.plan = [{**step, "status": "complete"} for step in job.plan]
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Published Superset virtual dataset {query_name}"}]
    audit(db, user, f"approval.{payload.decision}", "approval", approval.id)
    main.record_governance_event(
        "approval_decision",
        approval.action_type,
        payload.decision,
        project_id=project.id,
        user_id=user.id,
        session_id=job.id if job else approval.id,
        risk_level=approval.risk_level,
        approval_id=approval.id,
    )
    db.commit()
    workflow_id = None
    if job and payload.decision == "approved" and approval.action_type not in {"enable_ingestion_schedule", "deploy_pipeline", "tool_execution", "quality_remediation", "apply_retention", "publish_superset_query"}:
        try:
            workflow_id = await start_agent_workflow(job.id, job.title)
        except Exception as exc:
            job.status = "FAILED"
            job.progress = 100
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "error", "message": f"Temporal workflow start failed: {str(exc)[:500]}"}]
        if workflow_id:
            job.status = "QUEUED"
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Temporal workflow {workflow_id} started after approval"}]
        elif job.status != "FAILED":
            run_agent_plan_locally(job.id, job.title)
            db.refresh(job)
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Executed bounded local approval fallback"}]
        db.commit()
    return {
        "status": approval.status,
        "job_status": job.status if job else None,
        "workflow_id": workflow_id,
        "schedule_enabled": schedule.enabled if schedule else None,
    }
