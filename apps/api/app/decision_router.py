"""Scored, explainable routing for conversational requests.

Before this module, "which capability handles a request" was decided by the
screen the user happened to open: chat always generated SQL, agent runs were
gated by substring keyword matches, and query tools were never considered.
This module centralises that decision into one auditable function that
returns every candidate with a score and a reason, not just a winner.

Design constraints (deliberate):

* Deterministic risk first. ``assess_risk`` is word-boundary regex over action
  verbs. A decision model may *escalate* risk but can never lower it, because
  typed decision models are documented to be steerable by adversarial text.
* Pluggable scorer. ``local`` is a dependency-free lexical scorer. ``jev``
  delegates the route choice to a TypeSafe Jev-compatible decision endpoint
  and falls back to ``local`` on any error or timeout.
* Versioned policy. Weights, thresholds and the decision-model instructions
  live in a policy dict that can be replaced from ``DECISION_POLICY_PATH``;
  that file is the artifact an offline optimizer (GEPA / DSPy style) edits
  after replaying ``/router/decisions`` against feedback and evaluations.
* Recommend, don't auto-execute. Chat still runs the governed SQL path; tool
  and agent routes are surfaced as suggested actions until acceptance data
  justifies automation.
"""
from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentDefinition, QueryTool

ROUTES = ("sql_analysis", "query_tool", "agent_run", "clarify")

ROUTE_LABELS = {
    "sql_analysis": "Grounded SQL analysis",
    "query_tool": "Governed query tool",
    "agent_run": "Multi-step agent run",
    "clarify": "Ask a clarifying question",
}

# Action verbs that make a request consequential. Matched on word boundaries
# with inflections, so "rewrite", "executive" and "sender" no longer trigger.
RISK_TERMS = (
    "schedule",
    "write",
    "create table",
    "publish",
    "deploy",
    "execute",
    "delete",
    "drop",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "export",
    "send",
    "email",
    "update",
    "insert",
    "modify",
    "remove",
    "merge",
)

HIGH_RISK_TERMS = {"delete", "drop", "truncate", "alter", "grant", "revoke", "create table", "insert", "update", "merge"}

DEFAULT_POLICY: dict[str, Any] = {
    "version": "local-v1",
    "weights": {
        "grounding": 0.55,
        "analytic_intent": 0.35,
        "tool_match": 0.9,
        "agent_intent": 0.8,
    },
    "thresholds": {
        "clarify_below": 0.22,
        "tool_min_coverage": 0.5,
        "suggest_min": 0.35,
    },
    "instructions": (
        "Choose the single capability that should handle the user's request in a governed "
        "data workspace. sql_analysis answers read-only analytical questions over catalogued "
        "tables. query_tool runs a pre-approved, parameterised query whose description matches "
        "the request. agent_run is for multi-step objectives (build, investigate, schedule, "
        "publish). clarify is for requests too vague or unrelated to the catalog to answer."
    ),
}

ANALYTIC_TERMS = {
    "how", "many", "much", "count", "total", "sum", "average", "avg", "mean", "median",
    "top", "bottom", "list", "show", "trend", "compare", "by", "per", "breakdown",
    "distribution", "rate", "percent", "percentage", "growth", "which", "what", "who",
    "when", "max", "min", "highest", "lowest", "monthly", "weekly", "daily", "yearly",
}
AGENT_TERMS = {
    "build", "create", "generate", "investigate", "diagnose", "monitor", "automate",
    "pipeline", "schedule", "publish", "deploy", "migrate", "profile", "remediate",
    "fix", "clean", "document", "orchestrate", "backfill", "refresh", "notify",
}
STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "was",
    "were", "be", "me", "my", "i", "we", "our", "with", "from", "at", "this", "that",
    "it", "its", "as", "can", "you", "please", "give", "get", "all", "each", "do",
}


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", (text or "").lower()) if token not in STOPWORDS]


def _risk_pattern(term: str) -> re.Pattern[str]:
    words = term.split()
    last = words[-1]
    stem = last[:-1] if last.endswith("e") else last
    inflected = rf"(?:{re.escape(last)}(?:s|d|ed)?|{re.escape(stem)}(?:ing|es))"
    body = r"\s+".join([*map(re.escape, words[:-1]), inflected])
    return re.compile(rf"\b{body}\b", re.IGNORECASE)


_RISK_PATTERNS = [(term, _risk_pattern(term)) for term in RISK_TERMS]


# A negation directly before the verb ("without altering", "do not delete") is
# not a request to act. Kept deliberately tight: only an optional "any"/"the"
# may sit between them, so "without hesitation delete" still triggers.
_NEGATED = re.compile(r"\b(?:without|not|never|no|avoid|avoiding|don't|dont|doesn't|won't)\s+(?:any\s+|the\s+)?$", re.IGNORECASE)


def assess_risk(text: str) -> dict[str, Any]:
    """Deterministic risk triggers. Shared by chat routing and agent-run approval."""
    text = text or ""
    triggers = [
        term
        for term, pattern in _RISK_PATTERNS
        if any(not _NEGATED.search(text[max(0, match.start() - 40):match.start()]) for match in pattern.finditer(text))
    ]
    level = "high" if any(term in HIGH_RISK_TERMS for term in triggers) else ("medium" if triggers else "low")
    return {"level": level, "requires_approval": bool(triggers), "triggers": triggers}


@lru_cache(maxsize=4)
def _load_policy_file(path: str, mtime: float) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def active_policy() -> dict[str, Any]:
    path = os.getenv("DECISION_POLICY_PATH", "").strip()
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    if not path:
        return policy
    try:
        override = _load_policy_file(path, os.path.getmtime(path))
    except (OSError, ValueError):
        return policy
    for key in ("weights", "thresholds"):
        if isinstance(override.get(key), dict):
            policy[key].update({k: float(v) for k, v in override[key].items() if isinstance(v, (int, float))})
    for key in ("version", "instructions"):
        if isinstance(override.get(key), str) and override[key].strip():
            policy[key] = override[key].strip()
    return policy


def _grounding_strength(grounding: dict[str, Any] | None) -> tuple[float, list[str]]:
    """Normalise mixed vector (0-1) and keyword (integer count) scores to 0-1."""
    matches = (grounding or {}).get("catalog_matches") or []
    best = 0.0
    reasons: list[str] = []
    for match in matches[:5]:
        raw = float(match.get("score") or 0.0)
        normalised = raw if match.get("match_type") in {"vector", "hybrid"} and raw <= 1.0 else min(1.0, raw / 3.0)
        best = max(best, normalised)
    if matches:
        reasons.append(f"{len(matches)} catalog match(es); best {matches[0].get('relation', '?')}")
    if (grounding or {}).get("semantic_matches"):
        best = min(1.0, best + 0.15)
        reasons.append("semantic metric matched")
    if not matches:
        reasons.append("no catalog tables matched the question")
    return best, reasons


def _coverage(question_tokens: list[str], text: str) -> float:
    if not question_tokens:
        return 0.0
    haystack = set(_tokens(text))
    hits = sum(1 for token in set(question_tokens) if token in haystack or token.rstrip("s") in haystack)
    return hits / len(set(question_tokens))


def _required_params(schema: dict[str, Any] | None) -> list[str]:
    return list((schema or {}).get("required") or [])


def local_scores(
    question: str,
    grounding: dict[str, Any] | None,
    tools: list[QueryTool],
    agents: list[AgentDefinition],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    weights, thresholds = policy["weights"], policy["thresholds"]
    tokens = _tokens(question)
    token_set = set(tokens)
    candidates: list[dict[str, Any]] = []

    strength, grounding_reasons = _grounding_strength(grounding)
    analytic = min(1.0, len(token_set & ANALYTIC_TERMS) / 2) if tokens else 0.0
    if question.strip().endswith("?"):
        analytic = min(1.0, analytic + 0.25)
    sql_score = weights["grounding"] * strength + weights["analytic_intent"] * analytic
    candidates.append({
        "route": "sql_analysis",
        "score": round(sql_score, 4),
        "reasons": [*grounding_reasons, f"analytic intent {analytic:.2f}"],
    })

    for tool in tools:
        text = " ".join([tool.name.replace("_", " "), tool.description, tool.purpose, " ".join(tool.tags or []), tool.line_of_business])
        coverage = _coverage(tokens, text)
        if coverage < thresholds["tool_min_coverage"] / 2:
            continue
        required = _required_params(tool.parameter_schema)
        penalty = 0.15 * len(required)
        reasons = [f"{coverage:.0%} of question terms match tool metadata"]
        if required:
            reasons.append(f"needs parameters: {', '.join(required[:4])}")
        if tool.requires_approval:
            reasons.append("tool requires approval")
        candidates.append({
            "route": "query_tool",
            "target": {"id": tool.id, "name": tool.name, "description": tool.description[:240], "required_parameters": required, "requires_approval": tool.requires_approval},
            "score": round(max(0.0, weights["tool_match"] * coverage - penalty), 4),
            "reasons": reasons,
        })

    agent_hits = token_set & AGENT_TERMS
    multi_step = len(re.findall(r"\b(then|and then|after that|next)\b", question.lower())) + question.count(";")
    agent_intent = min(1.0, 0.45 * len(agent_hits) + 0.25 * multi_step)
    if agent_intent > 0:
        best_agent = None
        best_fit = 0.0
        for agent in agents:
            fit = _coverage(tokens, f"{agent.name} {agent.purpose}")
            if fit > best_fit:
                best_agent, best_fit = agent, fit
        reasons = [f"action verbs: {', '.join(sorted(agent_hits))}" if agent_hits else "multi-step phrasing"]
        if best_agent is not None and best_fit > 0:
            reasons.append(f"closest agent: {best_agent.name}")
        candidates.append({
            "route": "agent_run",
            "target": {"id": best_agent.id, "name": best_agent.name} if best_agent is not None and best_fit > 0 else None,
            "score": round(weights["agent_intent"] * agent_intent, 4),
            "reasons": reasons,
        })

    vague = len(tokens) <= 2 or (strength == 0 and analytic < 0.5)
    clarify_score = thresholds["clarify_below"] + (0.2 if vague else 0.0) - 0.1 * strength
    candidates.append({
        "route": "clarify",
        "score": round(max(0.0, clarify_score), 4),
        "reasons": ["question is short or not grounded in the catalog"] if vague else ["baseline"],
    })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def _jev_choice(question: str, candidates: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, float] | None:
    """Ask a Jev-compatible decision endpoint for a probability per candidate.

    Only trusted metadata goes into the state: the user's question and the
    registry descriptions. Tool output, query results and retrieved documents
    are excluded because they are the injection surface.

    The request/response shape follows TypeSafe's published concepts (state +
    typed ``choice`` question, probabilities per option). Verify it against the
    API reference for your account before enabling; parsing is tolerant and any
    mismatch falls back to the local scorer.
    """
    url = os.getenv("TYPESAFE_API_URL", "").strip()
    key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not url or not key:
        return None
    options = [_option_label(item) for item in candidates]
    payload = {
        "model": os.getenv("TYPESAFE_MODEL", "jev"),
        "state": {
            "request": question[:4_000],
            "capabilities": {label: "; ".join(item.get("reasons", []))[:400] for label, item in zip(options, candidates)},
        },
        "questions": {
            "route": {"type": "choice", "instructions": policy["instructions"], "options": options},
        },
    }
    timeout = float(os.getenv("TYPESAFE_TIMEOUT_SECONDS", "2.0"))
    try:
        response = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    answer = (body.get("answers") or body.get("results") or body.get("questions") or body).get("route") if isinstance(body, dict) else None
    distribution = None
    if isinstance(answer, dict):
        distribution = answer.get("probabilities") or answer.get("distribution")
    if not isinstance(distribution, dict):
        return None
    try:
        return {str(label): float(value) for label, value in distribution.items() if label in options}
    except (TypeError, ValueError):
        return None


def _llm_choice(question: str, candidates: list[dict[str, Any]], policy: dict[str, Any], provider: Any) -> dict[str, float] | None:
    """Ask the routed general-purpose model for a probability per option.

    Same trust boundary as Jev: only the question and the candidates' reasons
    (derived from registry metadata) are sent, never rows or retrieved text.
    """
    from .model_runtime import generate_text  # late import keeps this module dependency-light

    options = [_option_label(item) for item in candidates]
    state = {
        "request": question[:4_000],
        "options": {label: "; ".join(item.get("reasons", []))[:400] for label, item in zip(options, candidates)},
    }
    try:
        response = generate_text(
            provider,
            policy["instructions"] + ' Reply with JSON only: {"probabilities": {"<option>": <0..1>, ...}} using exactly the given option names; probabilities sum to 1.',
            json.dumps(state),
            300,
            governance_feature="decision_routing",
        )
        text = response.content.strip()
        text = text[text.find("{"): text.rfind("}") + 1]
        probabilities = json.loads(text).get("probabilities", {})
        cleaned = {str(label): max(0.0, float(value)) for label, value in probabilities.items() if label in options}
    except Exception:
        return None
    total = sum(cleaned.values())
    return {label: value / total for label, value in cleaned.items()} if total > 0 else None


def _option_label(candidate: dict[str, Any]) -> str:
    target = candidate.get("target") or {}
    return f"{candidate['route']}:{target['name']}" if target.get("name") else candidate["route"]


def decide(
    db: Session,
    project_id: str,
    question: str,
    grounding: dict[str, Any] | None = None,
    llm_provider: Any = None,
    backend_override: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    policy = active_policy()
    tools = db.scalars(
        select(QueryTool).where(QueryTool.project_id == project_id, QueryTool.status == "published")
    ).all()
    agents = db.scalars(select(AgentDefinition).where(AgentDefinition.enabled.is_(True))).all()
    candidates = local_scores(question, grounding, tools, agents, policy)[:6]
    backend = "local"
    requested = (backend_override or os.getenv("DECISION_ROUTER_BACKEND", "local")).strip().lower()
    if requested == "llm":
        distribution = _llm_choice(question, candidates, policy, llm_provider) if llm_provider is not None and getattr(llm_provider, "provider_type", "") != "local_mock" else None
        if distribution:
            backend = f"llm:{llm_provider.default_model}"
            for item in candidates:
                item["local_score"] = item["score"]
                item["score"] = round(distribution.get(_option_label(item), 0.0), 4)
            candidates.sort(key=lambda item: item["score"], reverse=True)
        else:
            backend = "local (llm unavailable)"
    elif requested == "jev":
        distribution = _jev_choice(question, candidates, policy)
        if distribution:
            backend = f"jev:{os.getenv('TYPESAFE_MODEL', 'jev')}"
            for item in candidates:
                item["local_score"] = item["score"]
                item["score"] = round(distribution.get(_option_label(item), 0.0), 4)
            candidates.sort(key=lambda item: item["score"], reverse=True)
        else:
            backend = "local (jev unavailable)"

    total = sum(item["score"] for item in candidates) or 1.0
    top = candidates[0]
    # Share of total score, damped when even the winner is weak in absolute
    # terms, so "best of several bad options" never reads as 100% confident.
    # Jev probabilities are already calibrated, so they are used as-is.
    share = top["score"] / total
    confidence = round(share if backend.startswith(("jev", "llm")) else share * min(1.0, top["score"] / 0.6), 4)
    risk = assess_risk(question)
    suggest_min = policy["thresholds"]["suggest_min"]
    suggestions = [
        {"route": item["route"], "label": ROUTE_LABELS[item["route"]], "target": item.get("target"), "score": item["score"], "reasons": item["reasons"]}
        for item in candidates
        if item["route"] in {"query_tool", "agent_run"} and item["score"] >= suggest_min * (1.0 if backend == "local" else 0.5)
    ][:3]
    return {
        "route": top["route"],
        "label": ROUTE_LABELS[top["route"]],
        "target": top.get("target"),
        "confidence": confidence,
        "candidates": candidates,
        "suggested_actions": suggestions,
        "risk": risk,
        "backend": backend,
        "policy_version": policy["version"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def follow_up_questions(question: str, execution: dict[str, Any] | None, limit: int = 3) -> list[str]:
    """Deterministic next questions derived from the result's actual columns."""
    if not execution or execution.get("error"):
        return ["Which tables contain this information?", "Show me the available columns for the closest table"][:limit]
    columns: list[str] = list(execution.get("columns") or [])
    rows = execution.get("rows") or []
    numeric = [c for c in columns if any(isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool) for r in rows[:50])]
    temporal = [c for c in columns if any(t in c.lower() for t in ("date", "day", "week", "month", "year", "time", "_at"))]
    categorical = [c for c in columns if c not in numeric and c not in temporal]
    ideas: list[str] = []
    if numeric and temporal:
        ideas.append(f"Show the trend of {numeric[0]} by {temporal[0]}")
    if numeric and categorical:
        ideas.append(f"Show the top 10 {categorical[0]} by {numeric[0]}")
    if categorical and len(categorical) > 1:
        ideas.append(f"Break this down by {categorical[1]}")
    measures = [c for c in numeric if not (c.lower() == "row_count" or c.lower().endswith("_count") or c.lower().endswith("_id"))]
    if measures:
        ideas.append(f"What is the average and total {measures[0]}?")
    if execution.get("row_count", 0) == 0:
        ideas.insert(0, "Why did this return no rows? Relax the filters")
    lowered = question.lower()
    return [idea for idea in ideas if idea.lower() not in lowered][:limit]
