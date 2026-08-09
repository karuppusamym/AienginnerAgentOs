"""Auto-extracted pipelines routes from the former monolithic main.py.

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


@router.get("/pipelines")
def list_pipelines(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    pipelines = db.scalars(select(PipelineDefinition).where(PipelineDefinition.project_id == project.id, PipelineDefinition.status != "deleted").order_by(PipelineDefinition.updated_at.desc())).all()
    return [pipeline_output(item, db) for item in pipelines]

@router.post("/pipelines/generate", status_code=201)
def generate_pipeline(payload: PipelineGenerateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_data_editor(user)
    project = require_current_project(db, user)
    assets = [db.get(DataAsset, asset_id) for asset_id in payload.source_asset_ids]
    if any(asset is None or asset.project_id != project.id for asset in assets):
        raise HTTPException(status_code=404, detail="A selected source dataset was not found")
    resolved_assets = [asset for asset in assets if asset is not None]
    approved_join_policies = db.scalars(
        select(SemanticJoinPolicy).where(
            SemanticJoinPolicy.project_id == project.id,
            SemanticJoinPolicy.status == "approved",
        )
    ).all()
    connectors_by_id = {
        asset.connector_id: db.get(Connector, asset.connector_id)
        for asset in resolved_assets
        if asset.connector_id
    }
    try:
        spec = plan_pipeline(
            objective=payload.objective,
            assets=resolved_assets,
            approved_join_policies=approved_join_policies,
            connectors_by_id=connectors_by_id,
            target_schema=payload.target_schema,
            target_table=payload.target_table,
            artifact_targets=payload.code_targets,
        )
        validate_pipeline_spec(spec)
        artifacts = emit_pipeline_artifacts(spec)
        validate_pipeline_artifacts(artifacts)
    except PipelineGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    generated_artifacts = [artifact.as_dict() for artifact in artifacts]
    generated_code = next(
        artifact.content for artifact in artifacts if artifact.key == "postgres_view"
    )
    definition = {
        "objective": payload.objective,
        "sources": [
            {
                "asset_id": source.asset_id,
                "relation": source.relation,
                "columns": source.columns,
            }
            for source in spec.sources
        ],
        "target": {
            "schema": spec.target_schema,
            "table": spec.target_table,
            "relation": spec.target_relation,
        },
        "nodes": spec.nodes,
        "edges": spec.edges,
        "joins": [
            {
                "left_relation": join.left_relation,
                "right_relation": join.right_relation,
                "left_key": join.left_key,
                "right_key": join.right_key,
                "join_type": join.join_type,
                "policy_id": join.policy_id,
                "source": join.source,
            }
            for join in spec.joins
        ],
        "checks": spec.checks,
        "deployment": {
            **spec.deployment,
            "artifact_count": len(generated_artifacts),
            "artifact_targets": sorted({artifact["target"] for artifact in generated_artifacts}),
        },
        "output_columns": spec.output_columns,
        "artifacts": generated_artifacts,
        "package_delivery": {
            target: _default_delivery_config(target)
            for target in sorted({artifact["target"] for artifact in generated_artifacts})
        },
    }
    artifact_content = json.dumps(
        {
            "definition": definition,
            "primary_artifact": "postgres_view",
            "generated_code": generated_code,
            "artifacts": generated_artifacts,
        },
        indent=2,
    )
    artifact, _ = save_internal_artifact_version(
        db,
        user,
        payload.name,
        "workflow",
        artifact_content,
        {
            "state": "draft",
            "source_asset_ids": payload.source_asset_ids,
            "artifact_targets": spec.artifact_targets,
        },
    )
    pipeline = PipelineDefinition(project_id=project.id, name=payload.name, objective=payload.objective, status="draft", current_version=1, artifact_id=artifact.id, created_by=user.id)
    db.add(pipeline)
    db.flush()
    db.add(PipelineVersion(pipeline_id=pipeline.id, version=1, definition=definition, generated_code=generated_code, created_by=user.id))
    for source in spec.sources:
        db.add(
            LineageEdge(
                project_id=project.id,
                pipeline_id=pipeline.id,
                source_asset_id=source.asset_id,
                source_relation=source.relation,
                target_relation=spec.target_relation,
                transformation="SELECT projection into governed view",
                column_mapping=spec.source_column_mappings.get(source.asset_id, []),
            )
        )
    audit(
        db,
        user,
        "pipeline.generated",
        "pipeline",
        pipeline.id,
        {"sources": [source.relation for source in spec.sources], "target": spec.target_relation},
    )
    db.commit()
    return pipeline_output(pipeline, db)

@router.get("/pipelines/{pipeline_id}/packages/{package_target}")
def get_pipeline_package(
    pipeline_id: str,
    package_target: Literal["postgres_view", "dbt", "dataform"],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _, pipeline, version = _get_project_pipeline_with_version(pipeline_id, user=user, db=db)
    package = _build_pipeline_package_or_404(pipeline, version, package_target)
    return {
        "pipeline_id": pipeline.id,
        "pipeline_version": pipeline.current_version,
        **package,
    }

@router.get("/pipelines/{pipeline_id}/packages/{package_target}/delivery-config")
def get_pipeline_package_delivery_config(
    pipeline_id: str,
    package_target: Literal["postgres_view", "dbt", "dataform"],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _, pipeline, version = _get_project_pipeline_with_version(pipeline_id, user=user, db=db)
    package = _build_pipeline_package_or_404(pipeline, version, package_target)
    return {
        "pipeline_id": pipeline.id,
        "pipeline_version": pipeline.current_version,
        "target": package_target,
        "delivery_config": package["delivery_config"],
        "delivery_plan": package["delivery_plan"],
    }

@router.put("/pipelines/{pipeline_id}/packages/{package_target}/delivery-config")
def save_pipeline_package_delivery_config(
    pipeline_id: str,
    package_target: Literal["postgres_view", "dbt", "dataform"],
    payload: PipelinePackageDeliveryConfigSave,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_data_editor(user)
    _, pipeline, version = _get_project_pipeline_with_version(pipeline_id, user=user, db=db)
    definition = json.loads(json.dumps(version.definition, default=str))
    if not definition.get("artifacts"):
        raise HTTPException(status_code=404, detail="Pipeline package artifacts were not generated")
    targets = {str(item.get("target")) for item in definition.get("artifacts", [])}
    if package_target not in targets:
        raise HTTPException(status_code=404, detail=f"Package target '{package_target}' is not available for this pipeline")
    package_delivery = dict(definition.get("package_delivery", {}))
    package_delivery[package_target] = _normalize_delivery_config(package_target, payload)
    definition["package_delivery"] = package_delivery
    version.definition = definition
    pipeline.updated_at = datetime.now(timezone.utc)
    if pipeline.artifact_id:
        save_internal_artifact_version(
            db,
            user,
            pipeline.name,
            "workflow",
            json.dumps(
                {
                    "definition": definition,
                    "primary_artifact": definition.get("deployment", {}).get("primary_artifact", "postgres_view"),
                    "generated_code": version.generated_code,
                    "artifacts": definition.get("artifacts", []),
                },
                indent=2,
            ),
            {
                "state": pipeline.status,
                "pipeline_id": pipeline.id,
                "pipeline_version": pipeline.current_version,
                "artifact_targets": definition.get("deployment", {}).get("supported_targets", []),
                "package_delivery_target": package_target,
            },
            artifact_id=pipeline.artifact_id,
        )
    audit(
        db,
        user,
        "pipeline.package_delivery_configured",
        "pipeline",
        pipeline.id,
        {"target": package_target, "delivery_mode": package_delivery[package_target]["delivery_mode"]},
    )
    db.commit()
    package = _build_pipeline_package_or_404(pipeline, version, package_target)
    return {
        "pipeline_id": pipeline.id,
        "pipeline_version": pipeline.current_version,
        "target": package_target,
        "delivery_config": package["delivery_config"],
        "delivery_plan": package["delivery_plan"],
    }

@router.get("/pipelines/{pipeline_id}/packages/{package_target}/archive")
def download_pipeline_package_archive(
    pipeline_id: str,
    package_target: Literal["postgres_view", "dbt", "dataform"],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    _, pipeline, version = _get_project_pipeline_with_version(pipeline_id, user=user, db=db)
    package = _build_pipeline_package_or_404(pipeline, version, package_target)
    archive_bytes = create_package_archive(
        build_exported_package(
            pipeline_name=pipeline.name,
            pipeline_version=pipeline.current_version,
            package_target=package_target,
            target_schema=str(version.definition.get("target", {}).get("schema", "curated")),
            target_table=str(version.definition.get("target", {}).get("table", "pipeline_output")),
            source_count=len(version.definition.get("sources", [])),
            artifacts=version.definition.get("artifacts", []),
            delivery_config=package["delivery_config"],
        )
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{package["archive_name"]}"',
    }
    return StreamingResponse(io.BytesIO(archive_bytes), media_type="application/zip", headers=headers)

@router.post("/pipelines/{pipeline_id}/packages/{package_target}/validate")
def validate_pipeline_package(
    pipeline_id: str,
    package_target: Literal["postgres_view", "dbt", "dataform"],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _, pipeline, version = _get_project_pipeline_with_version(pipeline_id, user=user, db=db)
    try:
        package = build_exported_package(
            pipeline_name=pipeline.name,
            pipeline_version=pipeline.current_version,
            package_target=package_target,
            target_schema=str(version.definition.get("target", {}).get("schema", "curated")),
            target_table=str(version.definition.get("target", {}).get("table", "pipeline_output")),
            source_count=len(version.definition.get("sources", [])),
            artifacts=version.definition.get("artifacts", []),
            delivery_config=_delivery_config_for_target(version.definition, package_target),
        )
    except PipelineGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    result = validate_exported_package(package)
    audit(
        db,
        user,
        "pipeline.package_validated",
        "pipeline",
        pipeline.id,
        {"target": package_target, "status": result.status, "version": pipeline.current_version},
    )
    db.commit()
    return {
        "pipeline_id": pipeline.id,
        "pipeline_version": pipeline.current_version,
        **result.as_dict(),
    }

@router.put("/pipelines/{pipeline_id}")
def update_pipeline(pipeline_id: str, payload: PipelineUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_data_editor(user)
    project = require_current_project(db, user)
    pipeline = db.get(PipelineDefinition, pipeline_id)
    if pipeline is None or pipeline.project_id != project.id or pipeline.status == "deleted":
        raise HTTPException(status_code=404, detail="Pipeline not found")
    current = db.scalar(select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version))
    if current is None:
        raise HTTPException(status_code=409, detail="Pipeline has no editable version")
    next_version = pipeline.current_version + 1
    definition = json.loads(json.dumps(current.definition, default=str))
    definition["objective"] = payload.objective
    pipeline.name = payload.name
    pipeline.objective = payload.objective
    pipeline.current_version = next_version
    pipeline.status = "draft"
    db.add(PipelineVersion(pipeline_id=pipeline.id, version=next_version, definition=definition, generated_code=current.generated_code, created_by=user.id))
    if pipeline.artifact_id:
        save_internal_artifact_version(
            db,
            user,
            payload.name,
            "workflow",
            json.dumps(
                {
                    "definition": definition,
                    "primary_artifact": definition.get("deployment", {}).get("primary_artifact", "postgres_view"),
                    "generated_code": current.generated_code,
                    "artifacts": definition.get("artifacts", []),
                },
                indent=2,
            ),
            {
                "state": "draft",
                "pipeline_id": pipeline.id,
                "pipeline_version": next_version,
                "artifact_targets": definition.get("deployment", {}).get("supported_targets", []),
            },
            artifact_id=pipeline.artifact_id,
        )
    audit(db, user, "pipeline.updated", "pipeline", pipeline.id, {"version": next_version})
    db.commit()
    return pipeline_output(pipeline, db)

@router.delete("/pipelines/{pipeline_id}")
def delete_pipeline(pipeline_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    require_data_editor(user)
    project = require_current_project(db, user)
    pipeline = db.get(PipelineDefinition, pipeline_id)
    if pipeline is None or pipeline.project_id != project.id or pipeline.status == "deleted":
        raise HTTPException(status_code=404, detail="Pipeline not found")
    pipeline.status = "deleted"
    audit(db, user, "pipeline.deleted", "pipeline", pipeline.id, {"version": pipeline.current_version})
    db.commit()
    return {"id": pipeline.id, "status": "deleted"}

@router.post("/pipelines/{pipeline_id}/deploy", status_code=201)
def request_pipeline_deployment(pipeline_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_data_editor(user)
    project = require_current_project(db, user)
    pipeline = db.get(PipelineDefinition, pipeline_id)
    if pipeline is None or pipeline.project_id != project.id:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    version = db.scalar(select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version))
    if version is None or not version.definition.get("deployment", {}).get("executable"):
        raise HTTPException(status_code=409, detail="Only validated local PostgreSQL pipelines can be deployed automatically")
    job = Job(project_id=project.id, title=f"Deploy pipeline: {pipeline.name}", job_type="pipeline_deployment", status="WAITING_FOR_APPROVAL", progress=60, plan=[{"agent": "Pipeline", "action": "Generate versioned transformation", "status": "complete"}, {"agent": "Quality", "action": "Validate source and target contract", "status": "complete"}, {"agent": "Policy", "action": "Approve local view creation", "status": "waiting"}], evidence=[{"type": "pipeline", "label": f"{pipeline.name} v{pipeline.current_version}"}, {"type": "target", "label": version.definition["target"]["relation"]}, *([{ "type": "joins", "label": f"{len(version.definition.get('joins', []))} governed joins"}] if version.definition.get("joins") else [])], created_by=user.id)
    db.add(job)
    db.flush()
    approval = Approval(project_id=project.id, job_id=job.id, title=f"Deploy {pipeline.name}", action_type="deploy_pipeline", risk_level="high", evidence={"pipeline_id": pipeline.id, "summary": f"Create governed local view {version.definition['target']['relation']}", "checks": ["catalog sources", "generated identifiers", "versioned SQL", "local PostgreSQL only", *( ["approved shared-key joins"] if version.definition.get("joins") else [])]}, requested_by=user.id)
    db.add(approval)
    pipeline.status = "awaiting_approval"
    audit(db, user, "pipeline.deployment_requested", "pipeline", pipeline.id, {"approval_id": approval.id})
    db.commit()
    return {"pipeline_id": pipeline.id, "job_id": job.id, "approval_id": approval.id, "status": pipeline.status}

@router.get("/lineage")
def get_lineage(relation: str | None = Query(default=None, max_length=320), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    edges = db.scalars(select(LineageEdge).where(LineageEdge.project_id == project.id).order_by(LineageEdge.created_at.desc())).all()
    if relation:
        normalized = relation.lower()
        edges = [edge for edge in edges if normalized in edge.source_relation.lower() or normalized in edge.target_relation.lower()]
    return {"nodes": sorted({value for edge in edges for value in (edge.source_relation, edge.target_relation)}), "edges": [as_dict(edge, ["id", "pipeline_id", "source_asset_id", "target_asset_id", "source_relation", "target_relation", "transformation", "column_mapping", "created_at"]) for edge in edges]}


@router.get("/lineage/graph")
def get_lineage_graph(
    relation: str = Query(min_length=1, max_length=320),
    direction: Literal["upstream", "downstream", "both"] = "both",
    depth: int = Query(default=5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Traverse multi-hop pipeline data-flow lineage from a relation.

    This is deliberately separate from ``/semantic/graph``: lineage follows
    physical pipeline edges, while semantic relationships describe governed
    business joins. Traversal is bounded to protect the API from accidental
    unbounded graph walks.
    """
    project = require_current_project(db, user)
    all_edges = db.scalars(select(LineageEdge).where(LineageEdge.project_id == project.id).order_by(LineageEdge.created_at)).all()
    anchor = relation.lower()
    adjacency: dict[str, list[tuple[LineageEdge, str, str]]] = {}
    for edge in all_edges:
        source = edge.source_relation
        target = edge.target_relation
        adjacency.setdefault(source.lower(), []).append((edge, "downstream", target))
        adjacency.setdefault(target.lower(), []).append((edge, "upstream", source))

    anchor_relations = sorted({relation_name for relation_name in adjacency if anchor in relation_name})
    if not anchor_relations:
        anchor_relations = [anchor]
    queue: list[tuple[str, int, str | None]] = [(item, 0, None) for item in anchor_relations]
    visited: set[tuple[str, str]] = set()
    selected: dict[str, dict[str, Any]] = {}
    node_depth: dict[str, int] = {item: 0 for item in anchor_relations}
    while queue:
        current, current_depth, _ = queue.pop(0)
        if current_depth >= depth:
            continue
        for edge, edge_direction, neighbor in adjacency.get(current.lower(), []):
            if direction != "both" and edge_direction != direction:
                continue
            visit_key = (edge.id, edge_direction)
            if visit_key in visited:
                continue
            visited.add(visit_key)
            hop = current_depth + 1
            selected_key = f"{edge.id}:{edge_direction}"
            selected[selected_key] = {
                **as_dict(edge, ["id", "pipeline_id", "source_asset_id", "target_asset_id", "source_relation", "target_relation", "transformation", "column_mapping", "created_at"]),
                "direction": edge_direction,
                "depth": hop,
            }
            node_depth[neighbor.lower()] = min(node_depth.get(neighbor.lower(), hop), hop)
            queue.append((neighbor.lower(), hop, edge.id))

    edge_items = list(selected.values())
    node_names = {relation}
    for edge in edge_items:
        node_names.update((edge["source_relation"], edge["target_relation"]))
    return {
        "relation": relation,
        "direction": direction,
        "depth": depth,
        "nodes": [{"relation": node, "depth": node_depth.get(node.lower(), 0)} for node in sorted(node_names)],
        "edges": edge_items,
        "truncated": any(item["depth"] == depth for item in edge_items),
    }
