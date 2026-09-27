"""Backward-compatible facade over the shared application services.

The helpers routers need used to live in this one ~1,860-line module. They now
live in cohesive modules under ``app/services/`` (authz, audit, outputs,
superset, connectors, security_overview, sql_service, agents, pipelines,
quality_rules, semantic, evaluations, query_tools, common). This module
re-exports every one of those names -- plus the third-party, model, schema and
runtime names routers have always pulled from here -- so ``from ..core import
...`` and ``from .. import core as main; main.X(...)`` keep working unchanged.

Late binding: a router calling ``main.execute_connector_query(...)`` looks the
name up on this module at call time, so patching ``app.core.X`` still affects
it. Code *inside* a service module reads its own module globals, so patch
``app.services.<module>.X`` for those call paths (for example
``app.services.query_tools.EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE`` or
``app.services.audit.current_membership``).

Services never import ``app.core`` or ``app.main``; add new shared code to a
service module and re-export it here only if routers need the old path.
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
from .decision_router import RISK_TERMS, assess_risk
from .request_context import active_project_id, is_production
from .migrations import migrations_on_startup, run_migrations
from .sql_guard import is_read_only
from .database import configure_read_only_access
import threading

from .schemas import *  # noqa: F401,F403  (re-exported for routers)
from .schemas import ORMModel  # noqa: F401

# Role model lives in roles.py; re-exported here for existing imports.
from .roles import ROLE_PERMISSIONS, default_membership_role, project_permissions  # noqa: E402

# generated_sql / generated_catalog_sql live in sql_generation.py so the tool
# registry's sql.generate builtin (tool_runtime.py) can import them without a
# circular import; re-exported under the same names for routers.
from .sql_generation import generated_catalog_sql, generated_sql  # noqa: E402

# --- Shared services (see app/services/) ---
from .services.common import (  # noqa: E402
    UPLOAD_DIR,
    as_dict,
    estimated_model_cost,
)
from .services.authz import (  # noqa: E402
    require_current_project,
    require_role,
    require_permission,
    require_any_permission,
    QUERY_RUNNERS,
    AGENT_RUNNERS,
    TOOL_RUNNERS,
    can_manage_shared_content,
    require_data_editor,
    require_workspace_editor,
    require_project_resource,
    require_semantic_maintainer,
    _external_client_from_header,
)
from .services.audit import (  # noqa: E402
    audit,
    save_internal_artifact_version,
)
from .services.outputs import (  # noqa: E402
    project_output,
    session_user_output,
    connector_output,
    external_extraction_output,
    schedule_output,
    pipeline_output,
    quality_rule_output,
    semantic_join_policy_output,
    external_client_output,
    query_tool_output,
    conversation_output,
)
from .services.superset import (  # noqa: E402
    _superset_dataset,
    resolve_superset_dataset,
    save_superset_dashboard_state,
    save_superset_query_dashboard_state,
)
from .services.connectors import (  # noqa: E402
    _validate_connector_contract,
    dataset_category,
    external_extraction_columns,
)
from .services.security_overview import (  # noqa: E402
    SECURITY_CATEGORIES,
    SECURITY_CATEGORY_LABELS,
    SECURITY_SEVERITIES,
    _security_bucket_label,
    _security_text,
    _security_category_from_incident,
    _security_score,
    _security_posture,
)
from .services.sql_service import (  # noqa: E402
    connector_dialect,
    analysis_source_output,
    refresh_conversation_summary,
    compact_conversation_context,
    SQL_GENERATOR_VERSION,
    SQL_CACHE_TTL_HOURS,
    _cacheable_sql_result,
    _sql_cache_key,
    _cached_sql_response,
    _store_sql_query_cache,
    conversational_analysis_answer,
    _extract_sql,
    _safe_read_only_sql,
    _column_sql_context_entry,
    _catalog_sql_context,
    _local_execution_error,
    _identifier_quote,
    _asset_relation_sql,
    _json_schema_type,
    _chart_from_result,
)
from .services.agents import (  # noqa: E402
    AGENT_APPROVAL_KEYWORDS,
    agent_run_requires_approval,
    initial_agent_plan,
)
from .services.pipelines import (  # noqa: E402
    _get_project_pipeline_with_version,
    _build_pipeline_package_or_404,
    _default_delivery_config,
    _normalize_delivery_config,
    _delivery_config_for_target,
    _build_delivery_plan,
)
from .services.quality_rules import (  # noqa: E402
    create_quality_rule_record,
)
from .services.semantic import (  # noqa: E402
    validate_semantic_join_policy,
    column_names_for_asset,
)
from .services.evaluations import (  # noqa: E402
    run_agent_evaluation_case,
)
from .services.query_tools import (  # noqa: E402
    _validate_query_tool_contract,
    _registry_metadata,
    _external_query_tool_output,
    _filter_registry_tools,
    _validate_tool_parameters,
    _granted_query_tools,
    EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE,
    _invoke_external_query_tool,
    query_tool_usage_summary,
)
