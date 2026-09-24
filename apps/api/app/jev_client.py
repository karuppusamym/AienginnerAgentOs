"""TypeSafe Jev decision model client (OpenRouter Decisions API).

Jev returns typed answers with probabilities instead of text:
- ``choice``: pick one option from ``criteria`` → {"choice", "probabilities", "confidence"}
- ``noul``: probability that a yes/no statement is true → {"noul"}
- ``score``: position on an ordered scale → {"score", "probabilities"}

DataPilot uses it for three decisions (each a routable model purpose):
``decision_routing`` (which capability answers a request), ``risk_check``
(is this a consequential action? — may only *escalate* approval), and
``sql_candidate_judge`` (tie-break when SQL candidates disagree).

Only trusted text goes into ``state`` (the user's question, registry
metadata, SQL text and column names) — never query result rows, tool output
or retrieved documents, which are the documented injection surface.
Every call is logged to ``model_call_logs`` with latency and cost.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

DEFAULT_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"  # pinned: aliases such as ~typesafe/jev-latest can shift verdicts


def _endpoint(provider: Any | None) -> tuple[str, str | None, str]:
    """URL, API key and model for a provider row (or the environment when none is declared)."""
    from .model_runtime import resolve_secret

    if provider is not None:
        return (
            (provider.base_url or DEFAULT_URL).rstrip("/"),
            resolve_secret(provider.secret_reference),
            provider.default_model or DEFAULT_MODEL,
        )
    return (
        os.getenv("TYPESAFE_API_URL", "").strip() or DEFAULT_URL,
        os.getenv("TYPESAFE_API_KEY", "").strip() or os.getenv("OPENROUTER_API_KEY", "").strip() or None,
        os.getenv("TYPESAFE_MODEL", "").strip() or DEFAULT_MODEL,
    )


def ask(provider: Any | None, state: dict[str, Any], questions: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
    """One Decisions API call. Returns {"ok", "answers", "model", "latency_ms", "cost_usd", "input_tokens", "output_tokens", "error"}."""
    url, key, model = _endpoint(provider)
    started = time.perf_counter()
    result: dict[str, Any] = {"ok": False, "answers": {}, "model": model, "latency_ms": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "error": None}
    if not key:
        result["error"] = "No API key for the Jev decision model (OPENROUTER_API_KEY or the provider secret)"
        return result
    try:
        response = httpx.post(
            url,
            json={"model": model, "state": state, "questions": questions},
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout or float(os.getenv("TYPESAFE_TIMEOUT_SECONDS", "3.0")),
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        return result
    usage = body.get("usage") or {}
    result.update(
        ok=isinstance(body.get("answers"), dict),
        answers=body.get("answers") or {},
        model=str(body.get("model") or model),
        latency_ms=round((time.perf_counter() - started) * 1000),
        cost_usd=float(usage.get("cost") or 0.0),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )
    if not result["ok"]:
        result["error"] = "Response had no answers"
    return result


def log_call(db: Any, provider: Any | None, purpose: str, result: dict[str, Any], project_id: str | None, user_id: str | None) -> None:
    """Record the call in model_call_logs (visible in Admin > Model usage). No-op without a declared provider."""
    if db is None or provider is None:
        return
    from .models import ModelCallLog

    db.add(ModelCallLog(
        project_id=project_id,
        provider_id=provider.id,
        model=result.get("model") or provider.default_model,
        purpose=purpose,
        status="healthy" if result.get("ok") else "failed",
        latency_ms=result.get("latency_ms"),
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
        estimated_cost_usd=result.get("cost_usd", 0.0),
        error=result.get("error"),
        created_by=user_id,
    ))


def consequential_probability(db: Any, provider: Any | None, text: str, project_id: str | None = None, user_id: str | None = None) -> tuple[float | None, str | None]:
    """P(text asks to change, delete, move, publish, schedule, send or grant). Used only to escalate risk."""
    result = ask(provider, {"request": text[:4_000]}, {
        "consequential": {
            "type": "noul",
            "instructions": "Does `request` ask to change, delete, move, publish, schedule, send or grant access to data or systems (not merely read or analyse)?",
        },
    })
    log_call(db, provider, "risk_check", result, project_id, user_id)
    value = (result["answers"].get("consequential") or {}).get("noul")
    return (float(value) if isinstance(value, (int, float)) else None), (result["model"] if result["ok"] else None)


def pick_candidate(db: Any, provider: Any | None, question: str, candidates: list[dict[str, Any]], project_id: str | None = None, user_id: str | None = None) -> dict[str, Any] | None:
    """Tie-break between SQL candidates: which SQL best answers the question? Uses SQL text and column names only."""
    options = {}
    for item in candidates:
        columns = list(((item.get("execution") or {}).get("columns") or []))[:12]
        options[item["model"][:60]] = f"SQL: {(item.get('sql') or '')[:1_200]} | result columns: {', '.join(columns)}"
    if len(options) < 2:
        return None
    result = ask(provider, {"question": question[:2_000]}, {
        "best_sql": {"type": "choice", "instructions": "Which SQL query answers `question` most correctly and directly?", "criteria": options},
    })
    log_call(db, provider, "sql_candidate_judge", result, project_id, user_id)
    answer = result["answers"].get("best_sql") or {}
    if not result["ok"] or not answer.get("choice"):
        return None
    return {"by": "jev", "model": result["model"], "choice": answer["choice"], "probabilities": answer.get("probabilities") or {}, "latency_ms": result["latency_ms"], "cost_usd": result["cost_usd"]}


def choose_tools(db: Any, provider: Any | None, step_action: str, objective: str, options: dict[str, str], project_id: str | None = None, user_id: str | None = None) -> dict[str, Any] | None:
    """Which of an agent's eligible tools fits this plan step? Uses the step text and registry descriptions only."""
    if len(options) < 2:
        return None
    result = ask(provider, {"step": step_action[:1_500], "objective": objective[:1_500]}, {
        "tool": {
            "type": "choice",
            "instructions": "Which tool should the agent call to carry out `step` (part of `objective`)? Pick the tool whose description fits the step best.",
            "criteria": {name[:80]: description[:400] for name, description in options.items()},
        },
    })
    log_call(db, provider, "tool_selection", result, project_id, user_id)
    answer = result["answers"].get("tool") or {}
    probabilities = answer.get("probabilities")
    if not result["ok"] or not isinstance(probabilities, dict):
        return None
    try:
        cleaned = {str(name): float(value) for name, value in probabilities.items() if name in options}
    except (TypeError, ValueError):
        return None
    return {"by": "jev", "model": result["model"], "probabilities": cleaned, "latency_ms": result["latency_ms"], "cost_usd": result["cost_usd"]} if cleaned else None
