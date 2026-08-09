"""Auto-extracted workspace routes from the former monolithic main.py.

Generated as part of the DataPilot backend restructuring effort
(docs/IMPLEMENTATION_STATUS_MATRIX.md, section 3). Behavior is unchanged;
route handlers were relocated verbatim from apps/api/app/main.py and now
live on a domain-scoped APIRouter instead of the global FastAPI app.
"""
from __future__ import annotations

import asyncio
import csv
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
    GlossaryDocument,
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
from ..vector_store import delete_document, index_document, search_documents
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
    DEFAULT_ARTIFACT_TARGETS, DataAsset, DataAssetUpdate, Depends, EvaluationBaselineRequest,
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


@router.get("/datasets")
def list_datasets(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    assets = db.scalars(
        select(DataAsset).where(DataAsset.project_id == project.id).order_by(DataAsset.schema_name, DataAsset.table_name)
    ).all()
    output = []
    for asset in assets:
        connector = db.get(Connector, asset.connector_id) if asset.connector_id else None
        source = analysis_source_output(connector, connector_dialect(connector, "postgres"))
        # A catalog asset's source is the registered database name; its type is
        # metadata, not an anonymous string copied into the dataset list.
        if connector is None and asset.source_name != "Local files":
            source["name"] = asset.source_name
            source["database"] = asset.source_name
        output.append(
            {
                **as_dict(
                    asset,
                    [
                        "id", "source_name", "schema_name", "table_name", "asset_type",
                        "row_count", "columns", "tags", "description", "connector_id",
                        "owner", "sensitivity", "freshness_sla_hours", "metadata_status",
                    ],
                ),
                "category": dataset_category(asset, connector),
                "source": source,
            }
        )
    return output


@router.put("/datasets/{asset_id}")
def update_dataset_metadata(
    asset_id: str,
    payload: DataAssetUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually review/correct catalog metadata for a scanned or staged asset.

    Closes a gap found during the Aug 8, 2026 metadata audit: DataAsset rows were
    write-only from the API's perspective (populated only by connector scan, file
    staging, or pipeline publish) with no way for a human to edit or enrich the
    description/tags afterward. See docs/IMPLEMENTATION_STATUS_MATRIX.md section 5.
    """
    require_data_editor(user)
    project = require_current_project(db, user)
    asset = db.get(DataAsset, asset_id)
    require_project_resource(asset, project, "Dataset")
    changes: dict[str, Any] = {}
    if payload.description is not None and payload.description != asset.description:
        changes["description"] = {"from": asset.description, "to": payload.description}
        asset.description = payload.description
    if payload.tags is not None and payload.tags != asset.tags:
        changes["tags"] = {"from": asset.tags, "to": payload.tags}
        asset.tags = payload.tags
    for field in ("owner", "sensitivity", "freshness_sla_hours", "metadata_status"):
        value = getattr(payload, field)
        if value is not None and value != getattr(asset, field):
            changes[field] = {"from": getattr(asset, field), "to": value}
            setattr(asset, field, value)
    if payload.column_notes is not None:
        allowed_keys = {"business_name", "description"}
        column_changes: dict[str, Any] = {}
        updated_columns = []
        for column in asset.columns:
            name = str(column.get("name", ""))
            notes = payload.column_notes.get(name)
            if not notes:
                updated_columns.append(column)
                continue
            invalid_keys = set(notes) - allowed_keys
            if invalid_keys:
                raise HTTPException(status_code=400, detail=f"column_notes only supports business_name/description (got: {', '.join(sorted(invalid_keys))})")
            merged = {**column, **notes}
            if merged != column:
                column_changes[name] = {key: {"from": column.get(key), "to": notes[key]} for key in notes if column.get(key) != notes[key]}
            updated_columns.append(merged)
        if column_changes:
            changes["columns"] = column_changes
            asset.columns = updated_columns
    if changes:
        audit(db, user, "dataset.metadata_updated", "data_asset", asset.id, changes)
        db.commit()
        db.refresh(asset)
    return as_dict(
        asset,
        ["id", "source_name", "schema_name", "table_name", "asset_type", "row_count", "columns", "tags", "description", "connector_id", "owner", "sensitivity", "freshness_sla_hours", "metadata_status"],
    )


@router.post("/datasets/import", status_code=201)
def import_dataset_metadata(
    file: UploadFile = File(...),
    source_name: str = Form("Manual catalog import"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Stand up a catalog entry from a description file, no live source needed.

    Closes the remaining metadata gap from docs/IMPLEMENTATION_STATUS_MATRIX.md
    section 5: "there is no way to hand DataPilot a schema/glossary file and
    have it populate the catalog without live data." This is the common
    enterprise-pilot path for a source DataPilot can't connect to live yet
    (credentials pending, network access pending, and so on) — someone
    exports a table/column/description sheet and imports it here.

    Expects a CSV with headers: schema_name, table_name, column_name
    (column_type, column_description, table_description, owner, sensitivity,
    tags are optional). One row per column; rows sharing a schema/table are
    grouped into a single DataAsset, created with metadata_status
    "manual_import" or updated if it already exists in this project.
    """
    require_data_editor(user)
    project = require_current_project(db, user)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".csv":
        raise HTTPException(status_code=400, detail="Upload a .csv file with schema_name, table_name, column_name columns")
    raw = file.file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded text")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not {"schema_name", "table_name", "column_name"}.issubset({(name or "").strip() for name in reader.fieldnames}):
        raise HTTPException(status_code=400, detail="CSV header must include schema_name, table_name, and column_name")

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    row_count = 0
    for row in reader:
        schema_name = (row.get("schema_name") or "").strip()
        table_name = (row.get("table_name") or "").strip()
        column_name = (row.get("column_name") or "").strip()
        if not schema_name or not table_name or not column_name:
            continue
        row_count += 1
        key = (schema_name, table_name)
        bucket = grouped.setdefault(
            key,
            {"columns": [], "description": None, "owner": None, "sensitivity": None, "tags": set()},
        )
        bucket["columns"].append(
            {
                "name": column_name,
                "type": (row.get("column_type") or "string").strip() or "string",
                "nullable": True,
                "description": (row.get("column_description") or "").strip() or None,
            }
        )
        if not bucket["description"] and (row.get("table_description") or "").strip():
            bucket["description"] = row["table_description"].strip()
        if not bucket["owner"] and (row.get("owner") or "").strip():
            bucket["owner"] = row["owner"].strip()
        if not bucket["sensitivity"] and (row.get("sensitivity") or "").strip():
            bucket["sensitivity"] = row["sensitivity"].strip()
        for tag in (row.get("tags") or "").split(","):
            tag = tag.strip()
            if tag:
                bucket["tags"].add(tag)

    if not grouped:
        raise HTTPException(status_code=400, detail="No usable rows found — check schema_name/table_name/column_name are populated")

    created = 0
    updated = 0
    for (schema_name, table_name), bucket in grouped.items():
        asset = db.scalar(
            select(DataAsset).where(
                DataAsset.project_id == project.id,
                DataAsset.schema_name == schema_name,
                DataAsset.table_name == table_name,
            )
        )
        if asset is None:
            asset = DataAsset(project_id=project.id, source_name=source_name, schema_name=schema_name, table_name=table_name, asset_type="imported")
            db.add(asset)
            created += 1
        else:
            updated += 1
        asset.columns = bucket["columns"]
        asset.tags = sorted(bucket["tags"]) or asset.tags
        if bucket["description"]:
            asset.description = bucket["description"]
        if bucket["owner"]:
            asset.owner = bucket["owner"]
        if bucket["sensitivity"]:
            asset.sensitivity = bucket["sensitivity"]
        asset.metadata_status = "manual_import"

    audit(db, user, "dataset.metadata_imported", "data_asset", None, {"source_name": source_name, "tables": len(grouped), "rows": row_count, "created": created, "updated": updated})
    db.commit()
    return {"tables": len(grouped), "columns_processed": row_count, "created": created, "updated": updated}


def _chunk_glossary_text(text: str, chunk_size: int = 1500, overlap: int = 150) -> list[str]:
    """Split into overlapping chunks so each vector point stays specific.

    embed_text() (see vector_store.py) is a bag-of-tokens hash, not a real
    semantic embedding — feeding it one giant multi-page document as a
    single point would dilute every chunk's distinguishing tokens into one
    blurry average vector. Indexing per-chunk keeps each point's vocabulary
    narrow enough for the hash-based scorer (and any real embedding model
    wired in later, see model_runtime.py) to actually discriminate between
    passages about different topics in the same document.
    """
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(normalized) <= chunk_size:
        return [normalized] if normalized else []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        boundary = normalized.rfind("\n\n", start, end)
        if boundary <= start:
            boundary = end
        chunks.append(normalized[start:boundary].strip())
        start = max(boundary - overlap, start + 1) if boundary < len(normalized) else end
    return [chunk for chunk in chunks if chunk]


@router.post("/glossary", status_code=201)
def upload_glossary_document(
    title: str = Form(...),
    file: UploadFile | None = File(default=None),
    text_content: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Upload a business glossary / SOP document to ground SQL generation and conversations.

    Closes a real gap: there was previously no way to give DataPilot
    unstructured business context (what a term means, a data-handling SOP,
    a definitions glossary) — only structured catalog metadata. Accepts
    either a .pdf/.txt/.md file or raw pasted text. Extracted text is
    chunked and indexed into the vector store (source_type="glossary"), and
    grounding_context() (see grounding.py) now retrieves matching chunks
    alongside catalog/semantic/join matches for SQL generation and the
    agent planner.
    """
    require_data_editor(user)
    project = require_current_project(db, user)
    if not file and not (text_content or "").strip():
        raise HTTPException(status_code=400, detail="Provide either a file or text_content")

    source_filename: str | None = None
    content_type = "text"
    if file is not None:
        source_filename = file.filename
        suffix = Path(file.filename or "").suffix.lower()
        raw = file.file.read()
        if suffix == ".pdf":
            content_type = "pdf"
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(raw))
                extracted = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Could not extract text from PDF: {exc}") from exc
        elif suffix in {".txt", ".md", ""}:
            try:
                extracted = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise HTTPException(status_code=400, detail="File must be UTF-8 encoded text") from None
        else:
            raise HTTPException(status_code=400, detail="Upload a .pdf, .txt, or .md file, or use text_content")
    else:
        extracted = text_content or ""

    extracted = extracted.strip()
    if not extracted:
        raise HTTPException(status_code=400, detail="No extractable text found")
    extracted = extracted[:60_000]

    document = GlossaryDocument(
        project_id=project.id,
        title=title.strip()[:200],
        source_filename=source_filename,
        content_type=content_type,
        extracted_text=extracted,
        character_count=len(extracted),
        created_by=user.id,
    )
    db.add(document)
    db.flush()

    chunks = _chunk_glossary_text(extracted)
    indexed_chunks = 0
    for index, chunk in enumerate(chunks):
        try:
            if index_document(
                f"{document.id}:chunk:{index}",
                document.title,
                chunk,
                {"source_type": "glossary", "document_id": document.id, "chunk_index": index, "chunk_count": len(chunks)},
            ):
                indexed_chunks += 1
        except Exception:
            pass  # indexing is best-effort; the document row is still saved either way

    audit(db, user, "glossary_document.uploaded", "glossary_document", document.id, {"title": document.title, "chunks": len(chunks), "indexed_chunks": indexed_chunks})
    db.commit()
    return {
        "id": document.id,
        "title": document.title,
        "source_filename": document.source_filename,
        "content_type": document.content_type,
        "character_count": document.character_count,
        "chunks": len(chunks),
        "indexed_chunks": indexed_chunks,
        "created_at": document.created_at.isoformat(),
    }


@router.get("/glossary")
def list_glossary_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    documents = db.scalars(
        select(GlossaryDocument).where(GlossaryDocument.project_id == project.id).order_by(GlossaryDocument.created_at.desc())
    ).all()
    return [
        {
            "id": document.id,
            "title": document.title,
            "source_filename": document.source_filename,
            "content_type": document.content_type,
            "character_count": document.character_count,
            "created_by": document.created_by,
            "created_at": document.created_at.isoformat(),
        }
        for document in documents
    ]


@router.delete("/glossary/{document_id}")
def delete_glossary_document(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_data_editor(user)
    project = require_current_project(db, user)
    document = db.get(GlossaryDocument, document_id)
    require_project_resource(document, project, "Glossary document")
    chunk_count = max(1, -(-document.character_count // 1500))  # best-effort upper bound on how many chunk points might exist
    for index in range(chunk_count):
        try:
            delete_document(f"{document.id}:chunk:{index}")
        except Exception:
            pass
    audit(db, user, "glossary_document.deleted", "glossary_document", document.id, {"title": document.title})
    db.delete(document)
    db.commit()
    return {"status": "deleted", "id": document_id}


@router.get("/recommendations")
def get_workspace_recommendations(
    limit: int = Query(default=3, ge=1, le=8),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return transparent, catalog-derived starting questions for this project.

    These are intentionally deterministic recommendations, not hidden model
    guesses. Each suggestion declares exactly which project metadata produced
    it so the UI can distinguish it from a generic sample prompt.
    """
    project = require_current_project(db, user)
    assets = db.scalars(
        select(DataAsset)
        .where(DataAsset.project_id == project.id)
        .order_by(DataAsset.schema_name, DataAsset.table_name)
        .limit(limit)
    ).all()
    suggestions: list[dict[str, str]] = []
    for asset in assets:
        relation = f"{asset.schema_name}.{asset.table_name}"
        columns = [str(column.get("name", "")) for column in asset.columns if column.get("name")]
        date_column = next((name for name in columns if any(token in name.lower() for token in ("date", "time", "month", "year", "created", "updated"))), None)
        if date_column:
            question = f"Show the trend in {relation} by {date_column} and highlight unusual changes"
        elif columns:
            question = f"Profile {relation}: row count, null rates, and the distribution of {columns[0]}"
        else:
            question = f"Profile the catalog metadata for {relation} and propose data-quality checks"
        suggestions.append({
            "question": question,
            "basis": f"Catalog metadata for {relation}" + (f" ({len(columns)} columns)" if columns else ""),
            "relation": relation,
        })
    if not suggestions:
        suggestions = [{
            "question": "Profile the latest local file and propose a staging schema",
            "basis": "No project dataset is cataloged yet",
            "relation": "",
        }]
    return {"project_id": project.id, "strategy": "catalog_metadata", "suggestions": suggestions}

@router.get("/search")
def search_workspace(
    q: str = Query(min_length=2, max_length=300),
    limit: int = Query(default=8, ge=1, le=25),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_current_project(db, user)
    vector_results = search_documents(q, limit)
    normalized = q.lower()
    keyword_results = []
    project_asset_ids: set[str] = set()
    for asset in db.scalars(select(DataAsset).where(DataAsset.project_id == project.id)).all():
        project_asset_ids.add(asset.id)
        haystack = " ".join(
            [
                asset.schema_name,
                asset.table_name,
                asset.description or "",
                " ".join(asset.tags),
                " ".join(str(column.get("name", "")) for column in asset.columns),
            ]
        ).lower()
        if all(token in haystack for token in normalized.split()):
            keyword_results.append(
                {
                    "source_id": asset.id,
                    "source_type": "dataset",
                    "title": f"{asset.schema_name}.{asset.table_name}",
                    "text": asset.description or "Catalog dataset",
                    "schema_name": asset.schema_name,
                    "table_name": asset.table_name,
                    "tags": asset.tags,
                    "score": 1.0,
                }
            )
    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in keyword_results + vector_results:
        source_id = str(result.get("source_id", ""))
        if result.get("source_type") == "dataset" and source_id not in project_asset_ids:
            continue
        if source_id and source_id not in seen:
            seen.add(source_id)
            combined.append(result)
    return {
        "query": q,
        "results": combined[:limit],
        "grounding": "keyword+vector" if vector_results else "keyword",
    }
