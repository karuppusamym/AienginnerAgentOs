"""Learning loop API: verified queries, GEPA prompt optimisation, index recommendations.

Everything that changes runtime behaviour goes through an approval:
prompt activation and index creation are applied in routers/approvals.py.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import core as main
from .. import learning
from ..auth import get_current_user
from ..database import engine, get_db
from ..gepa import run_optimization
from ..index_advisor import ddl_execution_allowed, recommend_indexes
from ..models import Approval, Job, PromptOptimizationRun, User, VerifiedQuery
from ..sql_guard import unknown_relations
from ..staging import execute_read_only

router = APIRouter()


def _verified_output(row: VerifiedQuery) -> dict[str, Any]:
    return main.as_dict(row, ["id", "question", "sql", "dialect", "connector_id", "source", "status", "uses", "last_used_at", "created_at"])


class VerifiedQueryCreate(BaseModel):
    question: str = Field(min_length=3, max_length=4_000)
    sql: str = Field(min_length=6, max_length=50_000)
    dialect: Literal["postgres", "sqlserver", "oracle", "teradata", "bigquery"] = "postgres"
    connector_id: str | None = None


class VerifiedQueryUpdate(BaseModel):
    status: Literal["active", "needs_review", "retired"]


@router.get("/verified-queries")
def list_verified_queries(status: str | None = Query(default=None, max_length=24), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = main.require_current_project(db, user)
    query = select(VerifiedQuery).where(VerifiedQuery.project_id == project.id)
    if status:
        query = query.where(VerifiedQuery.status == status)
    return [_verified_output(row) for row in db.scalars(query.order_by(VerifiedQuery.created_at.desc()).limit(500)).all()]


@router.post("/verified-queries", status_code=201)
def create_verified_query(payload: VerifiedQueryCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    main.require_data_editor(user, db)
    project = main.require_current_project(db, user)
    assets = db.scalars(select(main.DataAsset).where(main.DataAsset.project_id == project.id, main.DataAsset.connector_id == payload.connector_id if payload.connector_id else main.DataAsset.connector_id.is_(None))).all()
    allowed = {f"{asset.schema_name}.{asset.table_name}".lower() for asset in assets}
    if not main._safe_read_only_sql(payload.sql, payload.dialect):
        raise HTTPException(status_code=422, detail="SQL must be a single read-only SELECT")
    outside = unknown_relations(payload.sql, payload.dialect, allowed)
    if outside:
        raise HTTPException(status_code=422, detail=f"SQL references tables outside the catalog: {', '.join(outside)}")
    fingerprint = None
    if payload.connector_id is None and payload.dialect == "postgres":
        try:
            fingerprint = learning.result_fingerprint(execute_read_only(engine, payload.sql, 500))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"SQL did not execute: {str(exc).splitlines()[0][:300]}") from exc
    row = learning.upsert_verified(db, project.id, payload.question, payload.sql, payload.dialect, payload.connector_id, "manual", user.id, fingerprint=fingerprint)
    db.flush()
    main.audit(db, user, "verified_query.created", "verified_query", row.id, {"source": "manual"})
    db.commit()
    return _verified_output(row)


@router.put("/verified-queries/{query_id}")
def update_verified_query(query_id: str, payload: VerifiedQueryUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    main.require_data_editor(user, db)
    project = main.require_current_project(db, user)
    row = main.require_project_resource(db.get(VerifiedQuery, query_id), project, "Verified query")
    row.status = payload.status
    main.audit(db, user, "verified_query.status_changed", "verified_query", row.id, {"status": payload.status})
    db.commit()
    return _verified_output(row)


@router.delete("/verified-queries/{query_id}")
def delete_verified_query(query_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    main.require_data_editor(user, db)
    project = main.require_current_project(db, user)
    row = main.require_project_resource(db.get(VerifiedQuery, query_id), project, "Verified query")
    db.delete(row)
    main.audit(db, user, "verified_query.deleted", "verified_query", query_id)
    db.commit()
    return {"id": query_id, "status": "deleted"}


# ------------------------------------------------------------------ GEPA runs

class OptimizationCreate(BaseModel):
    purpose: Literal["sql_generation"] = "sql_generation"
    iterations: int = Field(default=4, ge=1, le=8)
    minibatch: int = Field(default=4, ge=2, le=8)
    evaluation_set_id: str | None = None
    include_verified: bool = True  # False: optimise against the chosen evaluation set only


class OptimizationApply(BaseModel):
    candidate_id: str | None = None


def _run_summary(run: PromptOptimizationRun) -> dict[str, Any]:
    return {
        **main.as_dict(run, ["id", "purpose", "status", "baseline_score", "best_score", "best_candidate_id", "iterations_done", "error", "created_at", "completed_at"]),
        "iterations": run.config.get("iterations"),
        "minibatch": run.config.get("minibatch"),
    }


def _require_optimizer(user: User, db: Session) -> None:
    if not main.can_manage_shared_content(user, db):
        raise HTTPException(status_code=403, detail="Only project owners, maintainers and admins can run prompt optimisation")


@router.post("/prompt-optimizations", status_code=202)
def start_prompt_optimization(payload: OptimizationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_optimizer(user, db)
    project = main.require_current_project(db, user)
    if db.scalar(select(PromptOptimizationRun).where(PromptOptimizationRun.project_id == project.id, PromptOptimizationRun.status.in_(["queued", "running"]))):
        raise HTTPException(status_code=409, detail="An optimisation is already running for this project")
    run = PromptOptimizationRun(project_id=project.id, purpose=payload.purpose, status="queued", config=payload.model_dump(), created_by=user.id)
    db.add(run)
    db.flush()
    main.audit(db, user, "prompt_optimization.started", "prompt_optimization", run.id, payload.model_dump())
    db.commit()
    threading.Thread(target=run_optimization, args=(run.id,), name=f"gepa-{run.id[:8]}", daemon=True).start()
    return _run_summary(run)


@router.get("/prompt-optimizations")
def list_prompt_optimizations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = main.require_current_project(db, user)
    runs = db.scalars(select(PromptOptimizationRun).where(PromptOptimizationRun.project_id == project.id).order_by(PromptOptimizationRun.created_at.desc()).limit(50)).all()
    return [_run_summary(run) for run in runs]


@router.get("/prompt-optimizations/{run_id}")
def get_prompt_optimization(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = main.require_current_project(db, user)
    run = main.require_project_resource(db.get(PromptOptimizationRun, run_id), project, "Optimisation run")
    return {**_run_summary(run), "cases": run.cases, "candidates": run.candidates, "log": run.log}


@router.post("/prompt-optimizations/{run_id}/apply", status_code=201)
def apply_prompt_optimization(run_id: str, payload: OptimizationApply, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Save the chosen candidate as a prompt version and request approval to activate it."""
    _require_optimizer(user, db)
    project = main.require_current_project(db, user)
    run = main.require_project_resource(db.get(PromptOptimizationRun, run_id), project, "Optimisation run")
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed optimisation runs can be applied")
    candidate_id = payload.candidate_id or run.best_candidate_id
    candidate = next((item for item in run.candidates or [] if item["id"] == candidate_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    name = learning.runtime_prompt_name(run.purpose)
    existing = db.scalar(select(main.Artifact).where(main.Artifact.project_id == project.id, main.Artifact.artifact_type == "prompt", main.Artifact.name == name))
    document = {"system_prompt": candidate["instructions"], "template": "{question}", "variables": ["question"]}
    artifact, version = main.save_internal_artifact_version(
        db, user, name, "prompt", json.dumps(document, indent=2),
        {"state": "pending_approval", "optimization_id": run.id, "candidate_id": candidate["id"], "mean_score": candidate["mean_score"], "baseline_score": run.baseline_score},
        existing.id if existing else None,
    )
    job = Job(project_id=project.id, title=f"Activate optimised {run.purpose} prompt v{version.version}", job_type="prompt_activation", status="WAITING_FOR_APPROVAL", progress=10, plan=[], evidence=[{"type": "optimization", "label": f"mean {candidate['mean_score']} vs baseline {run.baseline_score}"}], outputs=[], created_by=user.id)
    db.add(job)
    db.flush()
    approval = Approval(
        project_id=project.id, job_id=job.id, title=f"Activate optimised {run.purpose} prompt (v{version.version})", action_type="prompt_activation",
        risk_level="medium", requested_by=user.id,
        evidence={"prompt_name": name, "artifact_id": artifact.id, "version": version.version, "instructions": candidate["instructions"], "baseline_score": run.baseline_score, "best_score": candidate["mean_score"], "optimization_id": run.id},
    )
    db.add(approval)
    db.flush()
    main.audit(db, user, "prompt_optimization.apply_requested", "prompt_optimization", run.id, {"approval_id": approval.id, "version": version.version})
    db.commit()
    return {"approval_id": approval.id, "prompt_version": version.version}


# ------------------------------------------------------------------ index recommendations

class IndexApply(BaseModel):
    relation: str = Field(min_length=3, max_length=320)
    columns: list[str] = Field(min_length=1, max_length=4)


@router.get("/sql/index-recommendations")
def list_index_recommendations(min_ms: float | None = Query(default=None, ge=0, le=600_000), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Index suggestions from queries slower than SLOW_QUERY_MS (or ``min_ms``); DDL is advice, not executed."""
    project = main.require_current_project(db, user)
    return recommend_indexes(db, engine, project.id, min_ms=min_ms)


@router.post("/sql/index-recommendations/apply", status_code=201)
def save_index_suggestion(payload: IndexApply, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Save the suggested DDL for DBA review. Execution only exists behind ALLOW_DDL_EXECUTION=true + approval."""
    main.require_data_editor(user, db)
    project = main.require_current_project(db, user)
    match = next((item for item in recommend_indexes(db, engine, project.id, min_ms=0, limit=100) if item["relation"] == payload.relation.lower() and item["columns"] == [c.lower() for c in payload.columns]), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Not a current suggestion for this project")
    if ddl_execution_allowed() and match["source"] == "local":
        job = Job(project_id=project.id, title=f"Create index on {match['relation']} ({', '.join(match['columns'])})", job_type="index_creation", status="WAITING_FOR_APPROVAL", progress=10, plan=[], evidence=[{"type": "workload", "label": match["reason"]}], outputs=[], created_by=user.id)
        db.add(job)
        db.flush()
        approval = Approval(project_id=project.id, job_id=job.id, title=f"Create index on {match['relation']}", action_type="create_index", risk_level="medium", requested_by=user.id,
                            evidence={key: match[key] for key in ("relation", "columns", "statement", "occurrences", "avg_ms", "max_ms", "threshold_ms", "dialect")})
        db.add(approval)
        db.flush()
        main.audit(db, user, "index.requested", "approval", approval.id, {"relation": match["relation"], "columns": match["columns"]})
        db.commit()
        return {"approval_id": approval.id, "statement": match["statement"], "executed": False}
    rationale = (
        f"{match['reason']}. {match['slow_queries']} slow quer{'y' if match['slow_queries'] == 1 else 'ies'}"
        + (f" (avg {match['avg_ms']} ms, max {match['max_ms']} ms; threshold {match['threshold_ms']:g} ms)" if match["avg_ms"] is not None else "")
        + (f". {match['verify_note']}" if match.get("verify_note") else "")
    )
    content = "\n".join([
        "-- DataPilot DDL suggestion for DBA review (not executed)",
        f"-- Source: {match['source']} ({match['dialect']})",
        f"-- {rationale}",
        match["statement"],
        "",
    ])
    artifact, _version = main.save_internal_artifact_version(
        db, user, f"Index {match['relation']} ({', '.join(match['columns'])})", "ddl_suggestion", content,
        {**{key: match[key] for key in ("relation", "columns", "dialect", "source", "statement", "avg_ms", "max_ms", "threshold_ms", "slow_queries")}, "rationale": rationale, "state": "suggested"},
    )
    main.audit(db, user, "ddl.suggested", "artifact", artifact.id, {"relation": match["relation"], "columns": match["columns"]})
    db.commit()
    return {"suggestion_id": artifact.id, "statement": match["statement"], "executed": False}


@router.get("/sql/ddl-suggestions")
def list_ddl_suggestions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = main.require_current_project(db, user)
    artifacts = db.scalars(select(main.Artifact).where(main.Artifact.project_id == project.id, main.Artifact.artifact_type == "ddl_suggestion").order_by(main.Artifact.created_at.desc()).limit(200)).all()
    output = []
    for artifact in artifacts:
        version = db.scalar(select(main.ArtifactVersion).where(main.ArtifactVersion.artifact_id == artifact.id).order_by(main.ArtifactVersion.version.desc()).limit(1))
        meta = (version.artifact_metadata if version else {}) or {}
        output.append({"id": artifact.id, "relation": meta.get("relation"), "columns": meta.get("columns", []), "statement": meta.get("statement"), "rationale": meta.get("rationale"),
                       "dialect": meta.get("dialect"), "source": meta.get("source"), "created_at": artifact.created_at, "created_by": artifact.created_by})
    return output
