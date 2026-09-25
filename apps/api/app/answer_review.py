"""Automatic answer reviewer (the seeded "Reviewer" agent in the chat path).

After a chat answer is built (SQL + execution + narrative) it is scored in two layers:

1. Deterministic checks, computed locally from the full result:
   the SQL ran without error, rows came back when the question expects rows, the
   narrative's figures appear in the result, the SQL's tables match the grounding,
   and the answer is not the generic safety fallback.
2. A decision-model check through the model routed to ``answer_review`` (Jev by
   default; a text model is asked for JSON probabilities; with no route the review
   is deterministic only). The model sees only the question, the SQL text, result
   column names, the row count and the narrative with figures and result values
   masked -- never result rows.

Output (``structured["review"]``)::

    {verdict: ok|check|doubtful|unreviewed, score 0..1, checks[{name, passed, detail}],
     probabilities, by, model, latency_ms, cost_usd, warning}

``review_answer_safely`` never raises: any failure yields verdict ``unreviewed``.
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any

WARNING_PREFIX = "Reviewer: this may not answer the question"

_NUMBER = re.compile(r"(?<![A-Za-z_])[-+]?\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(%|percent\b|k\b|thousand\b|m\b|mn\b|million\b|bn\b|b\b|billion\b)?", re.I)
_MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_RELATION = re.compile(r"\b(?:from|join)\s+((?:[\"`\[]?[A-Za-z_][\w$]*[\"`\]]?\.){0,2}[\"`\[]?[A-Za-z_][\w$]*[\"`\]]?)", re.I)
_NO_ROWS_EXPECTED = re.compile(r"\b(are there any|is there any|is there an?|any\s+\w+\s+(?:with|where|that)|does .* exist|do any|whether)\b", re.I)


def review_timeout_seconds() -> float:
    try:
        return max(0.5, float(os.getenv("ANSWER_REVIEW_TIMEOUT_SECONDS", "4")))
    except ValueError:
        return 4.0


# ---------------------------------------------------------------- deterministic checks

def _numbers_in_text(text: str) -> list[tuple[float, str]]:
    found = []
    for match in _NUMBER.finditer(text or ""):
        whole, fraction, suffix = match.group(1), match.group(2) or "", (match.group(3) or "").lower()
        try:
            value = float(whole.replace(",", "") + fraction)
        except ValueError:
            continue
        if suffix in _MULTIPLIERS:
            value *= _MULTIPLIERS[suffix]
        found.append((value, match.group(0).strip()))
    return found


def _result_numbers(execution: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for row in (execution.get("rows") or [])[:500]:
        items = row.values() if isinstance(row, dict) else row if isinstance(row, (list, tuple)) else []
        for value in items:
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                values.append(float(value))
                continue
            try:
                values.append(float(str(value).replace(",", "")))
            except (TypeError, ValueError):
                # Dates and labels can carry figures too ("2024-03", "Q3 2024").
                values.extend(number for number, _ in _numbers_in_text(str(value)))
    values.append(float(execution.get("row_count") or len(execution.get("rows") or [])))
    return values


def _matches(value: float, candidates: list[float]) -> bool:
    for candidate in candidates:
        for scaled in (candidate, candidate * 100):  # 0.25 shown as 25%
            if abs(scaled - value) <= max(abs(scaled) * 0.01, 0.51):
                return True
    return False


def numbers_check(answer: str, question: str, sql: str, execution: dict[str, Any] | None) -> dict[str, Any]:
    if not execution or execution.get("error"):
        return {"name": "numbers_in_result", "passed": True, "detail": "No result to compare figures with"}
    allowed = [number for number, _ in _numbers_in_text(question)] + [number for number, _ in _numbers_in_text(sql)]
    result = _result_numbers(execution)
    # Single digits are mostly list positions ("1.", "top 3"); they are not compared.
    figures = [(value, raw) for value, raw in _numbers_in_text(answer) if abs(value) >= 10 or "." in raw or "%" in raw]
    if not figures:
        return {"name": "numbers_in_result", "passed": True, "detail": "The answer quotes no figures"}
    missing = [raw for value, raw in figures if not _matches(value, result) and not _matches(value, allowed)]
    if missing:
        return {"name": "numbers_in_result", "passed": False, "detail": f"{len(missing)} of {len(figures)} figures are not in the result: {', '.join(missing[:5])}"}
    return {"name": "numbers_in_result", "passed": True, "detail": f"All {len(figures)} figures appear in the result"}


def _normalise_relation(value: str) -> str:
    parts = [part.strip('"`[] ').lower() for part in str(value).split(".") if part.strip('"`[] ')]
    return ".".join(parts[-2:])


def sql_relations(sql: str) -> set[str]:
    ctes = {name.lower() for name in re.findall(r"(?:\bwith|,)\s*([A-Za-z_]\w*)\s+as\s*\(", sql or "", re.I)}
    relations = set()
    for raw in _RELATION.findall(sql or ""):
        relation = _normalise_relation(raw)
        if relation and relation.split(".")[-1] not in ctes and relation not in {"select", "lateral", "unnest"}:
            relations.add(relation)
    return relations


def tables_check(sql: str, grounding: dict[str, Any] | None) -> dict[str, Any]:
    matches = (grounding or {}).get("catalog_matches") or []
    grounded = {_normalise_relation(item.get("relation") or "") for item in matches if item.get("relation")}
    used = sql_relations(sql)
    if not used:
        return {"name": "tables_match_grounding", "passed": True, "detail": "The SQL reads no named table"}
    if not grounded:
        return {"name": "tables_match_grounding", "passed": True, "detail": "No grounding to compare with"}
    grounded_tables = {item.split(".")[-1] for item in grounded}
    unknown = sorted(item for item in used if item not in grounded and item.split(".")[-1] not in grounded_tables)
    if unknown:
        return {"name": "tables_match_grounding", "passed": False, "detail": f"Not among the grounded tables: {', '.join(unknown[:5])}"}
    return {"name": "tables_match_grounding", "passed": True, "detail": f"Reads {', '.join(sorted(used)[:5])}, all grounded"}


def deterministic_checks(question: str, analysis: dict[str, Any], execution: dict[str, Any] | None, answer: str, route: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    sql = str(analysis.get("sql") or "")
    checks: list[dict[str, Any]] = []
    if not execution:
        checks.append({"name": "sql_executed", "passed": False, "detail": "The SQL was not executed against a source"})
    elif execution.get("error"):
        checks.append({"name": "sql_executed", "passed": False, "critical": True, "detail": f"Execution failed: {str(execution.get('error'))[:160]}"})
    else:
        checks.append({"name": "sql_executed", "passed": True, "detail": "Executed without error"})
    row_count = int((execution or {}).get("row_count") or 0)
    expects_rows = not _NO_ROWS_EXPECTED.search(question or "")
    if execution and not execution.get("error"):
        if row_count > 0:
            checks.append({"name": "rows_returned", "passed": True, "detail": f"{row_count} row(s) returned"})
        elif expects_rows:
            checks.append({"name": "rows_returned", "passed": False, "detail": "No rows came back, but the question expects some"})
        else:
            checks.append({"name": "rows_returned", "passed": True, "detail": "No rows; the question asks whether any exist"})
    checks.append(numbers_check(answer, question, sql, execution))
    checks.append(tables_check(sql, analysis.get("grounding")))
    fallback = (analysis.get("provider") or {}).get("mode") == "deterministic_safety_fallback" or (analysis.get("validation") or {}).get("status") == "fallback"
    checks.append({"name": "not_fallback", "passed": not fallback, "detail": "Generic safety fallback query, not the model's SQL" if fallback else "Model SQL passed the safety checks"})
    if route is not None:
        unsure = route.get("route") == "clarify"
        checks.append({"name": "route_confident", "passed": not unsure, "detail": "The router could not ground the question (clarify)" if unsure else f"Routed to {route.get('route')}"})
    return checks


# ---------------------------------------------------------------- decision model

def _text_values(execution: dict[str, Any] | None) -> set[str]:
    values: set[str] = set()
    for row in ((execution or {}).get("rows") or [])[:500]:
        items = row.values() if isinstance(row, dict) else row if isinstance(row, (list, tuple)) else []
        for value in items:
            text = str(value).strip() if value is not None else ""
            if len(text) >= 3:
                values.add(text)
    return values


def mask_narrative(answer: str, execution: dict[str, Any] | None) -> str:
    """The narrative with result values and every digit masked, so no row value leaves the deployment."""
    masked = answer or ""
    for value in sorted(_text_values(execution), key=len, reverse=True)[:300]:
        masked = re.sub(re.escape(value), "[value]", masked, flags=re.I)
    return re.sub(r"\d", "#", masked)[:2_000]


def review_state(question: str, analysis: dict[str, Any], execution: dict[str, Any] | None, answer: str) -> dict[str, Any]:
    """What the decision model may see: question, SQL, column names, row count, masked narrative."""
    return {
        "question": (question or "")[:2_000],
        "sql": str(analysis.get("sql") or "")[:3_000],
        "columns": [str(column) for column in ((execution or {}).get("columns") or [])][:40],
        "row_count": int((execution or {}).get("row_count") or 0),
        "narrative": mask_narrative(answer, execution),
    }


def _text_model_review(db: Any, provider: Any, state: dict[str, Any], project_id: str | None, user_id: str | None, timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    from . import jev_client
    from .model_runtime import generate_text

    system = (
        "You review a data-analysis answer. You get the question, the SQL, the result column names, the row count and the "
        "narrative with figures masked as #. Reply with JSON only: "
        '{"answers_question": <0..1 probability the SQL and result answer the question>, '
        '"grounded": <0..1 probability the narrative is consistent with those columns and row count>}.'
    )
    started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(generate_text, provider, system, json.dumps(state), 120, governance_feature="answer_review", governance_user_id=user_id)
    error = None
    probabilities: dict[str, float] = {}
    try:
        content = future.result(timeout=timeout).content.strip()
        parsed = json.loads(content[content.find("{"): content.rfind("}") + 1])
        for name in ("answers_question", "grounded"):
            if isinstance(parsed.get(name), (int, float)):
                probabilities[name] = max(0.0, min(1.0, float(parsed[name])))
        if not probabilities:
            error = "Response had no review probabilities"
    except FutureTimeout:
        error = f"Timed out after {timeout:g}s"
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        executor.shutdown(wait=False)
    latency_ms = round((time.perf_counter() - started) * 1000)
    jev_client.log_call(db, provider, "answer_review", {"ok": error is None, "model": getattr(provider, "default_model", ""), "latency_ms": latency_ms, "error": error}, project_id, user_id)
    if error:
        return None, error
    return {"by": "llm", "model": getattr(provider, "default_model", ""), "probabilities": probabilities, "latency_ms": latency_ms, "cost_usd": 0.0}, None


def model_review(db: Any, provider: Any, state: dict[str, Any], project_id: str | None, user_id: str | None) -> tuple[dict[str, Any] | None, str | None]:
    from . import jev_client
    from .provider_selection import provider_capability

    if provider is None:
        return None, None
    capability = provider_capability(provider)
    if capability == "local":
        return None, None  # routed to the on-prem deterministic model: deterministic checks only
    if capability == "decision":
        return jev_client.review_answer_with_error(db, provider, state, project_id, user_id, timeout=review_timeout_seconds())
    return _text_model_review(db, provider, state, project_id, user_id, review_timeout_seconds())


# ---------------------------------------------------------------- verdict

_CHECK_WEIGHTS = {"sql_executed": 3.0, "rows_returned": 2.0, "numbers_in_result": 2.0, "tables_match_grounding": 1.0, "not_fallback": 2.0, "route_confident": 1.0}


def verdict_for(checks: list[dict[str, Any]], probabilities: dict[str, float]) -> tuple[str, float]:
    total = sum(_CHECK_WEIGHTS.get(item["name"], 1.0) for item in checks) or 1.0
    deterministic = sum(_CHECK_WEIGHTS.get(item["name"], 1.0) for item in checks if item["passed"]) / total
    score = deterministic
    if probabilities:
        score = 0.5 * deterministic + 0.5 * (sum(probabilities.values()) / len(probabilities))
    failed = {item["name"] for item in checks if not item["passed"]}
    answers = probabilities.get("answers_question")
    critical = any(item.get("critical") and not item["passed"] for item in checks)
    if critical or (answers is not None and answers < 0.35) or score < 0.5:
        return "doubtful", round(score, 3)
    if failed or score < 0.75 or (answers is not None and answers < 0.6):
        return "check", round(score, 3)
    return "ok", round(score, 3)


def _warning(checks: list[dict[str, Any]], probabilities: dict[str, float]) -> str:
    reasons = [item["detail"] for item in checks if not item["passed"]]
    if probabilities.get("answers_question") is not None and probabilities["answers_question"] < 0.5:
        reasons.append(f"the decision model gives only {round(probabilities['answers_question'] * 100)}% that the query answers the question")
    reason = "; ".join(reason[:1].lower() + reason[1:] for reason in reasons[:3]) or "low review score"
    return f"{WARNING_PREFIX} — {reason}."


def review_answer(db: Any, provider: Any, question: str, analysis: dict[str, Any], execution: dict[str, Any] | None, answer: str, project_id: str | None = None, user_id: str | None = None, route: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    checks = deterministic_checks(question, analysis, execution, answer, route)
    verdict_model, model_error = model_review(db, provider, review_state(question, analysis, execution, answer), project_id, user_id)
    probabilities = (verdict_model or {}).get("probabilities") or {}
    verdict, score = verdict_for(checks, probabilities)
    review = {
        "verdict": verdict,
        "score": score,
        "checks": checks,
        "probabilities": probabilities,
        "by": (verdict_model or {}).get("by") or "deterministic",
        "model": (verdict_model or {}).get("model") or (getattr(provider, "default_model", None) if provider is not None else None),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "cost_usd": float((verdict_model or {}).get("cost_usd") or 0.0),
        "model_error": model_error,
        "warning": None,
    }
    if verdict == "doubtful":
        review["warning"] = _warning(checks, probabilities)
    return review


def review_answer_safely(db: Any, user: Any, project_id: str | None, question: str, analysis: dict[str, Any], execution: dict[str, Any] | None, answer: str, route: dict[str, Any] | None = None) -> dict[str, Any]:
    """``review_answer`` with the routed provider; never raises (verdict ``unreviewed`` on any failure)."""
    started = time.perf_counter()
    try:
        from .provider_selection import routed_only_provider

        try:
            provider = routed_only_provider(db, user, "answer_review") if user is not None else None
        except Exception:
            provider = None
        return review_answer(db, provider, question, analysis, execution, answer, project_id, getattr(user, "id", None), route)
    except Exception as exc:  # the review must never break the answer
        return {
            "verdict": "unreviewed", "score": None, "checks": [], "probabilities": {}, "by": "none", "model": None,
            "latency_ms": round((time.perf_counter() - started) * 1000), "cost_usd": 0.0,
            "model_error": f"{type(exc).__name__}: {str(exc)[:200]}", "warning": None,
        }
