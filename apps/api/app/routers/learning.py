"""Learning loop API: verified queries, GEPA prompt optimisation, index recommendations, SQL tuning.

Everything that changes runtime behaviour goes through an approval:
prompt activation and index creation are applied in routers/approvals.py.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import core as main
from .. import learning
from .. import query_tuner
from ..auth import get_current_user
from ..database import engine, get_db
from ..gepa import run_optimization
from ..index_advisor import ddl_execution_allowed, recommend_indexes, slow_query_threshold_ms
from ..models import Approval, Connector, Job, PromptOptimizationRun, QueryRun, User, VerifiedQuery
from ..pagination import Page, contains, grouped_counts, page_params, paginate_query
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
def list_verified_queries(response: Response, page: Page = Depends(page_params), status: str | None = Query(default=None, max_length=24), source: str = Query(default="", max_length=32), q: str = Query(default="", max_length=200), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = main.require_current_project(db, user)
    query = select(VerifiedQuery).where(VerifiedQuery.project_id == project.id)
    if status:
        query = query.where(VerifiedQuery.status == status)
    if source:
        query = query.where(VerifiedQuery.source == source)
    if q.strip():
        query = query.where(func.lower(VerifiedQuery.question).like(contains(q), escape="\\") | func.lower(VerifiedQuery.sql).like(contains(q), escape="\\"))
    return [_verified_output(row) for row in paginate_query(db, query.order_by(VerifiedQuery.created_at.desc()), response, page, default_limit=500)]


@router.get("/verified-queries/facets")
def verified_query_facets(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Counts per status and source (the status filter's badges) without loading the list."""
    project = main.require_current_project(db, user)
    scoped = select(VerifiedQuery).where(VerifiedQuery.project_id == project.id).subquery()
    by_status = db.execute(select(scoped.c.status, func.count()).group_by(scoped.c.status)).all()
    by_source = db.execute(select(scoped.c.source, func.count()).group_by(scoped.c.source)).all()
    return {"total": sum(count for _, count in by_status), "status": grouped_counts(by_status), "source": grouped_counts(by_source)}


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


# ------------------------------------------------------------------ SQL tuning (equivalent faster rewrites)

class SqlTuneCreate(BaseModel):
    sql: str | None = Field(default=None, min_length=6, max_length=400_000)  # pasted queries can run to thousands of lines
    query_run_id: str | None = Field(default=None, max_length=36)
    question: str | None = Field(default=None, max_length=4_000)
    dialect: Literal["postgres", "sqlserver", "oracle", "teradata", "bigquery"] | None = None
    connector_id: str | None = Field(default=None, max_length=36)
    iterations: int = Field(default=query_tuner.DEFAULT_ITERATIONS, ge=1, le=query_tuner.MAX_ITERATIONS)


class SqlTuneApply(BaseModel):
    question: str | None = Field(default=None, min_length=3, max_length=4_000)


def _require_query_runner(user: User, db: Session) -> None:
    main.require_any_permission(user, db, main.QUERY_RUNNERS, "Your role can read results but cannot run SQL tuning")


def _tuning_job(db: Session, project, job_id: str) -> Job:
    job = main.require_project_resource(db.get(Job, job_id), project, "Tuning run")
    if job.job_type != query_tuner.JOB_TYPE:
        raise HTTPException(status_code=404, detail="Tuning run not found")
    return job


def _rewrite_approvals(db: Session, project_id: str, job_id: str) -> list[Approval]:
    approvals = db.scalars(select(Approval).where(Approval.project_id == project_id, Approval.action_type == query_tuner.APPROVAL_ACTION).order_by(Approval.created_at.desc()).limit(200)).all()
    return [item for item in approvals if (item.evidence or {}).get("tuning_job_id") == job_id]


def _tuning_summary(job: Job) -> dict[str, Any]:
    request = query_tuner.job_request(job)
    report = query_tuner.job_report(job) or {}
    return {
        "id": job.id, "status": job.status, "progress": job.progress, "created_at": job.created_at, "updated_at": job.updated_at,
        "sql": (request.get("sql") or "")[:2_000], "question": request.get("question"), "connector_id": request.get("connector_id"), "query_run_id": request.get("query_run_id"),
        "result": report.get("status"), "baseline_ms": report.get("baseline_ms"), "best_ms": report.get("best_ms"), "speedup_pct": report.get("speedup_pct"), "error": report.get("error"),
    }


@router.get("/sql/slow-queries")
def list_slow_queries(min_ms: float | None = Query(default=None, ge=0, le=600_000), limit: int = Query(default=25, ge=1, le=100), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Recent query runs at or over SLOW_QUERY_MS (or ``min_ms``), grouped by SQL, slowest first."""
    project = main.require_current_project(db, user)
    threshold = slow_query_threshold_ms() if min_ms is None else float(min_ms)
    runs = db.scalars(select(QueryRun).where(QueryRun.project_id == project.id, QueryRun.status.in_(["generated", "cache_hit"])).order_by(QueryRun.created_at.desc()).limit(500)).all()
    groups: dict[tuple, dict[str, Any]] = {}
    for run in runs:
        execution = (run.result or {}).get("execution") or {}
        duration = execution.get("duration_ms")
        if not run.sql or execution.get("error") or duration is None or float(duration) < threshold:
            continue
        key = (" ".join(run.sql.split()).lower(), run.connector_id, run.dialect)
        group = groups.setdefault(key, {"sql": run.sql, "question": run.question, "dialect": run.dialect, "connector_id": run.connector_id, "query_run_id": run.id, "last_run_at": run.created_at, "durations": []})
        group["durations"].append(float(duration))
    output = []
    for group in groups.values():
        durations = group.pop("durations")
        output.append({**group, "count": len(durations), "avg_ms": round(sum(durations) / len(durations), 1), "max_ms": round(max(durations), 1), "threshold_ms": threshold})
    output.sort(key=lambda item: item["avg_ms"], reverse=True)
    return output[:limit]


@router.post("/sql/tune", status_code=202)
def start_sql_tuning(payload: SqlTuneCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Queue a plan-guided tuning run (background). Nothing is applied; see /sql/tune/{id}/apply."""
    _require_query_runner(user, db)
    project = main.require_current_project(db, user)
    sql, question, dialect, connector_id = payload.sql, payload.question, payload.dialect, payload.connector_id
    if payload.query_run_id:
        run = main.require_project_resource(db.get(QueryRun, payload.query_run_id), project, "Query run")
        sql, question = sql or run.sql, question or run.question
        dialect, connector_id = dialect or run.dialect, connector_id or run.connector_id
    if not sql:
        raise HTTPException(status_code=422, detail="Provide sql or query_run_id")
    connector = main.require_project_resource(db.get(Connector, connector_id), project, "Connector") if connector_id else None
    dialect = main.connector_dialect(connector, dialect or "postgres")
    local = connector is None or connector.connector_type == "local_files"
    allowed = {f"{asset.schema_name}.{asset.table_name}".lower() for asset in query_tuner.catalog_for(db, project.id, connector)}
    problem = query_tuner.guard_candidate(sql, "postgres" if local else dialect, allowed)
    if problem:
        raise HTTPException(status_code=422, detail=f"SQL cannot be tuned: {problem}")
    provider = main.selected_model_provider(db, user, "sql_tuning")
    if provider is None or provider.provider_type in {"local_mock", "jev"}:
        raise HTTPException(status_code=409, detail="Route a text-generation model to 'SQL tuning' in Admin > Model routing first")
    if db.scalar(select(Job).where(Job.project_id == project.id, Job.job_type == query_tuner.JOB_TYPE, Job.status.in_(["QUEUED", "RUNNING"]))):
        raise HTTPException(status_code=409, detail="A tuning run is already in progress for this project")
    config = {"sql": sql.strip().rstrip(";"), "question": question, "dialect": dialect, "connector_id": connector.id if connector is not None and not local else None,
              "query_run_id": payload.query_run_id, "iterations": payload.iterations}
    job = Job(project_id=project.id, title=f"Tune SQL: {(question or ' '.join(sql.split()))[:180]}", job_type=query_tuner.JOB_TYPE, status="QUEUED", progress=0, plan=[],
              evidence=[{"type": "sql_tuning_request", "label": f"{payload.iterations} attempts on {connector.name if connector is not None else 'local workspace'}", "config": config}],
              logs=[], outputs=[], created_by=user.id)
    db.add(job)
    db.flush()
    main.audit(db, user, "sql_tuning.started", "job", job.id, {"iterations": payload.iterations, "connector_id": config["connector_id"], "query_run_id": payload.query_run_id})
    db.commit()
    threading.Thread(target=query_tuner.run_tuning_job, args=(job.id,), name=f"sqltune-{job.id[:8]}", daemon=True).start()
    return _tuning_summary(job)


@router.get("/sql/tune")
def list_sql_tuning_runs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = main.require_current_project(db, user)
    jobs = db.scalars(select(Job).where(Job.project_id == project.id, Job.job_type == query_tuner.JOB_TYPE).order_by(Job.created_at.desc()).limit(50)).all()
    return [_tuning_summary(job) for job in jobs]


@router.get("/sql/tune/{job_id}")
def get_sql_tuning_run(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = main.require_current_project(db, user)
    job = _tuning_job(db, project, job_id)
    approvals = _rewrite_approvals(db, project.id, job.id)
    latest = approvals[0] if approvals else None
    return {
        **_tuning_summary(job), "logs": job.logs or [], "request": query_tuner.job_request(job), "report": query_tuner.job_report(job),
        "approval": {"id": latest.id, "status": latest.status, "created_at": latest.created_at} if latest else None,
    }


@router.post("/sql/tune/{job_id}/apply", status_code=201)
def apply_sql_tuning(job_id: str, payload: SqlTuneApply, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Request approval to make the winning rewrite the verified query for its question (never automatic)."""
    main.require_data_editor(user, db)
    project = main.require_current_project(db, user)
    job = _tuning_job(db, project, job_id)
    report = query_tuner.job_report(job) or {}
    if job.status != "SUCCEEDED" or report.get("status") != "improved" or not report.get("winning_sql"):
        raise HTTPException(status_code=409, detail="Only a completed run that found a faster equivalent rewrite can be applied")
    if any(item.status == "pending" for item in _rewrite_approvals(db, project.id, job.id)):
        raise HTTPException(status_code=409, detail="An approval for this rewrite is already pending")
    if not query_tuner.approval_hook_installed():
        raise HTTPException(status_code=503, detail="Rewrite activation approvals are not enabled on this server (routers/approvals.py has no sql_rewrite_activation handler)")
    question = payload.question or report.get("question")
    if not question:
        raise HTTPException(status_code=422, detail="This SQL has no recorded question: provide the question the verified query should answer")
    connector = db.get(Connector, report["connector_id"]) if report.get("connector_id") else None
    allowed = {f"{asset.schema_name}.{asset.table_name}".lower() for asset in query_tuner.catalog_for(db, project.id, connector)}
    problem = query_tuner.guard_candidate(report["winning_sql"], report.get("dialect") or "postgres", allowed)
    if problem:
        raise HTTPException(status_code=409, detail=f"The winning SQL no longer passes validation: {problem}")
    dialect = report.get("dialect") or "postgres"
    existing = learning.exact_verified(db, project.id, question, dialect, report.get("connector_id"))
    evidence = {
        "tuning_job_id": job.id, "question": question, "sql": report["winning_sql"], "original_sql": report.get("original_sql"), "dialect": dialect,
        "connector_id": report.get("connector_id"), "baseline_ms": report.get("baseline_ms"), "best_ms": report.get("best_ms"), "speedup_pct": report.get("speedup_pct"),
        "replaces_verified_query_id": existing.id if existing else None, "plan_diff": report.get("plan_diff", [])[:12],
    }
    title = f"Activate tuned SQL ({report.get('speedup_pct')}% faster) for: {question}"[:200]
    activation = Job(project_id=project.id, title=title, job_type=query_tuner.APPROVAL_ACTION, status="WAITING_FOR_APPROVAL", progress=10, plan=[],
                     evidence=[{"type": "sql_tuning", "label": f"{report.get('baseline_ms')} ms → {report.get('best_ms')} ms, results verified equivalent", "tuning_job_id": job.id}], outputs=[], created_by=user.id)
    db.add(activation)
    db.flush()
    approval = Approval(project_id=project.id, job_id=activation.id, title=title, action_type=query_tuner.APPROVAL_ACTION, risk_level="medium", requested_by=user.id, evidence=evidence)
    db.add(approval)
    db.flush()
    main.audit(db, user, "sql_rewrite.apply_requested", "job", job.id, {"approval_id": approval.id, "speedup_pct": report.get("speedup_pct")})
    db.commit()
    return {"approval_id": approval.id, "replaces_verified_query_id": evidence["replaces_verified_query_id"]}
