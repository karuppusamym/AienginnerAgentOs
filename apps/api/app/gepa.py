"""GEPA-style optimisation of the SQL-generation instruction.

GEPA (Genetic-Pareto prompt evolution) improves a prompt by *reflection*
rather than gradient search:

1. Evaluate the current instruction on real cases and keep a per-case score.
2. Pick a parent from the Pareto front (candidates that are best on at least
   one case), weighted by how many cases they win.
3. Run the parent on a small minibatch, collect its failures with concrete
   feedback (SQL error, missing tables, wrong result), and ask a strong
   "reflection" model to rewrite the instruction to fix them.
4. Keep the child only if it beats the parent on that minibatch; then score it
   on all cases and add it to the pool.
5. Repeat for a fixed budget. The best-mean candidate is proposed.

Governance: this module never activates anything. The proposal becomes a
prompt version that only goes live through an approval, and the fixed safety
clause (learning.SQL_SAFETY_CLAUSE) is appended at runtime regardless of what
the optimiser writes.

Cases come from SQL evaluation sets (expected tables/tokens) and from
verified queries (expected result = the verified SQL's result fingerprint).
"""
from __future__ import annotations

import json
import random
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import learning
from .database import SessionLocal
from .grounding import grounding_context, grounding_prompt_text
from .model_runtime import generate_text
from .models import Connector, DataAsset, EvaluationSet, ModelProvider, Project, PromptOptimizationRun, User, VerifiedQuery
from .provider_selection import selected_model_provider
from .request_context import active_project_id
from .sql_guard import check_read_only, unknown_relations
from .staging import execute_read_only

MAX_CASES = 24

REFLECTION_SYSTEM = (
    "You improve the instruction given to a text-to-SQL model in a governed analytics platform. "
    "You will see the current instruction and concrete failures with feedback. Write an improved "
    "instruction that fixes the failure patterns while keeping what works. Be specific about SQL "
    "habits (joins, grouping, date handling, filters, naming, limits). Do not mention the examples "
    "verbatim and do not include safety rules (they are appended separately). Return only the new "
    "instruction text, under 1,200 characters."
)


def _log(run: PromptOptimizationRun, message: str) -> None:
    run.log = [*(run.log or []), {"at": datetime.now(timezone.utc).isoformat(), "message": message[:500]}]


def _extract_sql(text: str) -> str:
    from .core import _extract_sql as extract  # late import: core is the shared facade

    return extract(text)


def build_cases(db: Session, project_id: str, evaluation_set_id: str | None, include_verified: bool = True) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    sets = db.scalars(select(EvaluationSet).where(EvaluationSet.project_id == project_id, *( [EvaluationSet.id == evaluation_set_id] if evaluation_set_id else []))).all()
    for evaluation_set in sets:
        for index, case in enumerate(evaluation_set.cases or []):
            tokens = case.get("required_sql_tokens") or case.get("expected_tokens") or []
            if case.get("question") and (case.get("expected_tables") or tokens) and case.get("case_type", "sql_generation") == "sql_generation" and not case.get("expected_agents"):
                cases.append({
                    "id": f"eval:{evaluation_set.id[:8]}:{index}",
                    "question": str(case["question"])[:1_000],
                    "dialect": case.get("dialect") or "postgres",
                    "expected_tables": [str(item).lower() for item in case.get("expected_tables", [])],
                    "expected_tokens": [str(item).lower() for item in tokens],
                    "expected_fingerprint": None,
                    "expected_execution": None,
                    "source": "evaluation",
                })
    for verified in [] if not include_verified else db.scalars(
        select(VerifiedQuery).where(VerifiedQuery.project_id == project_id, VerifiedQuery.status == "active", VerifiedQuery.connector_id.is_(None), VerifiedQuery.dialect == "postgres")
        .order_by(VerifiedQuery.uses.desc(), VerifiedQuery.created_at.desc()).limit(MAX_CASES)
    ).all():
        try:
            expected_execution = execute_read_only(_engine(), verified.sql, 500)
        except Exception:
            expected_execution = None
        fingerprint = learning.result_fingerprint(expected_execution) if expected_execution else verified.result_fingerprint
        verdict = check_read_only(verified.sql, "postgres")
        cases.append({
            "id": f"verified:{verified.id[:8]}",
            "question": verified.question[:1_000],
            "dialect": "postgres",
            "expected_tables": [f"{schema}.{table}" if schema else table for schema, table in verdict.relations] if verdict.ok else [],
            "expected_tokens": [],
            "expected_fingerprint": fingerprint,
            "expected_execution": {"rows": (expected_execution or {}).get("rows", [])} if expected_execution else None,
            "source": "verified",
        })
    return cases[:MAX_CASES]


def _engine():
    from .database import engine

    return engine


def score_case(case: dict[str, Any], sql: str, allowed: set[str]) -> tuple[float, str]:
    """0..1 score and a human-readable feedback line for the reflection model."""
    verdict = check_read_only(sql, "postgres")
    if not sql or not verdict.ok:
        return 0.0, f"not a valid read-only SELECT ({verdict.reason or 'empty'})"
    if unknown_relations(sql, "postgres", allowed):
        return 0.0, f"referenced tables outside the catalog: {', '.join(unknown_relations(sql, 'postgres', allowed))}"
    try:
        execution = execute_read_only(_engine(), sql, 500)
    except Exception as exc:
        return 0.1, f"execution failed: {str(exc).splitlines()[0][:200]}"
    parts, feedback = [0.4], []
    referenced = {f"{schema}.{table}" if schema else table for schema, table in verdict.relations}
    if case["expected_tables"]:
        hit = sum(1 for table in case["expected_tables"] if table in referenced or table.split(".")[-1] in {r.split(".")[-1] for r in referenced})
        parts.append(0.2 * hit / len(case["expected_tables"]))
        if hit < len(case["expected_tables"]):
            feedback.append(f"expected tables {case['expected_tables']} but used {sorted(referenced)}")
    else:
        parts.append(0.2)
    lowered = sql.lower()
    if case["expected_tokens"]:
        hit = sum(1 for token in case["expected_tokens"] if token in lowered)
        parts.append(0.1 * hit / len(case["expected_tokens"]))
        missing = [token for token in case["expected_tokens"] if token not in lowered]
        if missing:
            feedback.append(f"missing expected elements {missing}")
    else:
        parts.append(0.1)
    if case.get("expected_execution") or case["expected_fingerprint"]:
        matches = learning.results_agree(execution, case["expected_execution"]) if case.get("expected_execution") else learning.result_fingerprint(execution) == case["expected_fingerprint"]
        if matches:
            parts.append(0.3)
        else:
            feedback.append(f"result differs from the verified answer ({execution.get('row_count')} rows returned)")
    else:
        parts.append(0.3 if execution.get("row_count") else 0.15)
    return round(min(1.0, sum(parts)), 4), "; ".join(feedback) or "correct"


class _Evaluator:
    def __init__(self, db: Session, project_id: str, provider: ModelProvider, cases: list[dict[str, Any]]):
        self.db, self.project_id, self.provider, self.cases = db, project_id, provider, cases
        assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project_id, DataAsset.connector_id.is_(None))).all()
        from .core import _catalog_sql_context

        self.catalog_text = _catalog_sql_context(assets)
        self.allowed = {f"{asset.schema_name}.{asset.table_name}".lower() for asset in assets}
        self.grounding = {case["id"]: grounding_prompt_text(grounding_context(db, project_id, case["question"], limit=5)) for case in cases}
        self.calls = 0

    def run(self, instructions: str, case: dict[str, Any]) -> tuple[float, str, str]:
        examples = learning.similar_verified(self.db, self.project_id, case["question"], "postgres", None, exclude_question=case["question"])
        prompt = learning.sql_user_prompt("postgres", case["question"], {"name": "DataPilot local workspace", "dialect": "postgres"}, "", self.catalog_text, self.grounding[case["id"]], examples)
        self.calls += 1
        try:
            sql = _extract_sql(generate_text(self.provider, learning.sql_system_prompt(instructions), prompt, 1200, governance_feature="prompt_optimization").content)
        except Exception as exc:
            return 0.0, f"model call failed: {str(exc)[:160]}", ""
        score, feedback = score_case(case, sql, self.allowed)
        return score, feedback, sql


def _pareto_front(candidates: list[dict[str, Any]], case_ids: list[str]) -> list[str]:
    front: set[str] = set()
    for case_id in case_ids:
        best = max((candidate["scores"].get(case_id, 0.0) for candidate in candidates), default=0.0)
        front.update(candidate["id"] for candidate in candidates if candidate["scores"].get(case_id, 0.0) == best and best > 0)
    return sorted(front) or [candidates[0]["id"]]


def run_optimization(run_id: str) -> None:
    """Background entry point: executes the whole optimisation and stores progress on the run row."""
    with SessionLocal() as db:
        run = db.get(PromptOptimizationRun, run_id)
        if run is None:
            return
        token = active_project_id.set(run.project_id)
        try:
            run.status = "running"
            _log(run, "Optimisation started")
            db.commit()
            user = db.get(User, run.created_by)
            provider = selected_model_provider(db, user, "sql_generation")
            try:
                reflector = selected_model_provider(db, user, "sql_repair") or provider
            except Exception:
                reflector = provider
            if provider is None or provider.provider_type == "local_mock":
                raise RuntimeError("Prompt optimisation needs a real model routed to sql_generation")
            cases = build_cases(db, run.project_id, run.config.get("evaluation_set_id"), run.config.get("include_verified", True))
            if len(cases) < 2:
                raise RuntimeError("Need at least 2 cases: add SQL evaluation cases or verified queries first")
            run.cases = [{"id": case["id"], "question": case["question"], "source": case["source"]} for case in cases]
            _log(run, f"{len(cases)} cases; generator {provider.name}; reflector {reflector.name}")
            db.commit()
            evaluator = _Evaluator(db, run.project_id, provider, cases)
            guidance, _ = learning.active_runtime_prompt(db, run.project_id, run.purpose)
            baseline = {"id": str(uuid4()), "parent_id": None, "origin": "baseline", "instructions": guidance or learning.DEFAULT_SQL_GUIDANCE, "scores": {}, "sql": {}}
            for case in cases:
                score, _feedback, sql = evaluator.run(baseline["instructions"], case)
                baseline["scores"][case["id"]] = score
                baseline["sql"][case["id"]] = sql
            pool = [baseline]
            case_ids = [case["id"] for case in cases]
            mean = lambda candidate: round(sum(candidate["scores"].values()) / len(case_ids), 4)
            run.baseline_score = mean(baseline)
            _log(run, f"Baseline mean score {run.baseline_score}")
            db.commit()
            rng = random.Random(run.id)
            iterations = int(run.config.get("iterations", 4))
            minibatch_size = int(run.config.get("minibatch", 4))
            for iteration in range(iterations):
                front = _pareto_front(pool, case_ids)
                wins = {candidate_id: sum(1 for case_id in case_ids if max(c["scores"].get(case_id, 0) for c in pool) == next(c for c in pool if c["id"] == candidate_id)["scores"].get(case_id, 0)) for candidate_id in front}
                parent_id = rng.choices(front, weights=[max(1, wins[item]) for item in front])[0]
                parent = next(candidate for candidate in pool if candidate["id"] == parent_id)
                batch = rng.sample(cases, min(minibatch_size, len(cases)))
                failures = []
                for case in batch:
                    score, feedback, sql = parent["scores"].get(case["id"]), None, parent["sql"].get(case["id"], "")
                    _, feedback = score_case(case, sql, evaluator.allowed) if sql else (0.0, "no SQL produced")
                    if score is None or score < 1.0:
                        failures.append({"question": case["question"], "sql": sql[:1_500], "feedback": feedback, "score": score})
                if not failures:
                    _log(run, f"Iteration {iteration + 1}: parent solved the minibatch; skipping reflection")
                    run.iterations_done = iteration + 1
                    db.commit()
                    continue
                try:
                    reflection = generate_text(
                        reflector,
                        REFLECTION_SYSTEM,
                        json.dumps({"current_instruction": parent["instructions"], "failures": failures}, default=str)[:14_000],
                        700,
                        governance_feature="prompt_optimization_reflection",
                    ).content.strip()
                except Exception as exc:
                    _log(run, f"Iteration {iteration + 1}: reflection failed ({str(exc)[:120]})")
                    continue
                child = {"id": str(uuid4()), "parent_id": parent["id"], "origin": "reflection", "instructions": reflection[:2_000], "scores": {}, "sql": {}}
                parent_batch = sum(parent["scores"].get(case["id"], 0.0) for case in batch)
                child_batch = 0.0
                for case in batch:
                    score, _feedback, sql = evaluator.run(child["instructions"], case)
                    child["scores"][case["id"]], child["sql"][case["id"]] = score, sql
                    child_batch += score
                if child_batch <= parent_batch:
                    _log(run, f"Iteration {iteration + 1}: child {child_batch:.2f} did not beat parent {parent_batch:.2f} on the minibatch; discarded")
                else:
                    for case in cases:
                        if case["id"] not in child["scores"]:
                            score, _feedback, sql = evaluator.run(child["instructions"], case)
                            child["scores"][case["id"]], child["sql"][case["id"]] = score, sql
                    pool.append(child)
                    _log(run, f"Iteration {iteration + 1}: child accepted, mean {mean(child)} (parent {mean(parent)})")
                run.iterations_done = iteration + 1
                run.candidates = _serialise(pool, case_ids, mean)
                db.commit()
            best = max(pool, key=mean)
            run.candidates = _serialise(pool, case_ids, mean)
            run.best_candidate_id = best["id"]
            run.best_score = mean(best)
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            _log(run, f"Completed after {evaluator.calls} generation calls; best mean {run.best_score} vs baseline {run.baseline_score}")
            db.commit()
        except Exception as exc:
            db.rollback()
            run = db.get(PromptOptimizationRun, run_id)
            run.status = "failed"
            run.error = str(exc)[:1_000]
            _log(run, f"Failed: {str(exc)[:300]}")
            print(traceback.format_exc()[-1500:])
            db.commit()
        finally:
            active_project_id.reset(token)


def _serialise(pool: list[dict[str, Any]], case_ids: list[str], mean) -> list[dict[str, Any]]:
    front = set(_pareto_front(pool, case_ids))
    return [
        {"id": c["id"], "parent_id": c["parent_id"], "origin": c["origin"], "instructions": c["instructions"], "scores": c["scores"], "mean_score": mean(c), "on_pareto_front": c["id"] in front}
        for c in pool
    ]
