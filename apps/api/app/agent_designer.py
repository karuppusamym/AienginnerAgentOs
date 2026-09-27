"""Agent designer: "build the purpose on first insert".

- ``draft_agent``: from a name and a one-or-two-sentence brief, draft the purpose,
  instructions, an autonomy suggestion and tool bindings. Tools come ONLY from the
  registry (enabled internal tools + this project's published query tools): the Jev
  model routed to ``tool_selection`` scores them when available, otherwise the text
  model routed to ``agent_design`` picks from the listed names, otherwise a local word
  overlap does. Every name is validated; unknown names are dropped and reported.
- ``draft_query_tool``: from SQL or a question, draft the purpose, description, tags,
  parameter schema (parameters must appear in the SQL) and line of business.
- ``suggest_purpose``: a purpose from just an agent name (auto-fill on create).

Nothing is saved here; callers return drafts for a human to review.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .model_runtime import generate_text
from .models import QueryTool, ToolDefinition, User

_WORD = re.compile(r"[a-z][a-z0-9]+")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "agent", "data", "tool", "tools", "each", "any", "are", "all", "its", "their", "use", "uses", "using", "run", "runs"}
_CONSEQUENTIAL = re.compile(r"\b(delete|drop|write|update|insert|publish|send|email|schedule|stage|load|move|copy|grant|deploy|execute)\b", re.I)
_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")
_RELATION = re.compile(r"\b(?:from|join)\s+((?:[\"`\[]?[A-Za-z_][\w$]*[\"`\]]?\.){0,2}[\"`\[]?[A-Za-z_][\w$]*[\"`\]]?)", re.I)
_LINES_OF_BUSINESS = [
    ("Retail Banking", {"account", "accounts", "transaction", "transactions", "deposit", "branch", "balance", "loan", "loans", "card", "cards"}),
    ("Finance", {"revenue", "invoice", "invoices", "ledger", "budget", "cost", "costs", "margin", "payment", "payments"}),
    ("Sales", {"order", "orders", "sales", "customer", "customers", "product", "products", "pipeline", "deal"}),
    ("Risk & Compliance", {"risk", "fraud", "aml", "kyc", "compliance", "audit", "policy", "breach"}),
    ("Operations", {"job", "jobs", "pipeline", "load", "loads", "incident", "sla", "quality", "schedule"}),
    ("Human Resources", {"employee", "employees", "payroll", "headcount", "hire", "attrition"}),
]


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall((text or "").lower()) if word not in _STOP}


def _json_object(content: str) -> dict[str, Any] | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (content or "").strip(), flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def design_provider(db: Session, user: User | None) -> Any | None:
    """The text model routed to ``agent_design`` (else the default text model), or None."""
    if user is None:
        return None
    from .provider_selection import provider_capability, selected_model_provider

    try:
        provider = selected_model_provider(db, user, "agent_design")
    except Exception:
        try:
            provider = selected_model_provider(db, user)
        except Exception:
            return None
    if provider is None or provider_capability(provider) != "generation":
        return None  # the local deterministic model and Jev cannot write prose
    return provider


def _generate(db: Session, provider: Any, system: str, prompt: str, max_tokens: int, project_id: str | None, user_id: str | None, deadline: float | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """generate_text -> parsed JSON object, logged as purpose ``agent_design``; an optional deadline in seconds."""
    from . import jev_client

    started = time.perf_counter()
    error = None
    parsed = None
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(generate_text, provider, system, prompt, max_tokens, governance_feature="agent_design", governance_user_id=user_id)
        content = future.result(timeout=deadline).content
        parsed = _json_object(content)
        if parsed is None:
            error = "The model did not return a JSON object"
    except FutureTimeout:
        error = f"Timed out after {deadline:g}s"
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        executor.shutdown(wait=False)
    jev_client.log_call(db, provider, "agent_design", {"ok": error is None, "model": getattr(provider, "default_model", ""), "latency_ms": round((time.perf_counter() - started) * 1000), "error": error}, project_id, user_id)
    return parsed, error


# ---------------------------------------------------------------- registry

def registry_tools(db: Session, project_id: str | None) -> dict[str, dict[str, Any]]:
    """Every tool an agent may be bound to: enabled internal tools, then published project query tools."""
    tools: dict[str, dict[str, Any]] = {}
    for tool in db.scalars(select(ToolDefinition).where(ToolDefinition.enabled.is_(True)).order_by(ToolDefinition.name)).all():
        tools[tool.name] = {"kind": "tool", "description": tool.description or tool.category, "risk_level": tool.risk_level, "requires_approval": bool(tool.requires_approval)}
    if project_id:
        for tool in db.scalars(select(QueryTool).where(QueryTool.project_id == project_id, QueryTool.status == "published").order_by(QueryTool.name)).all():
            tools.setdefault(tool.name, {"kind": "query_tool", "description": tool.purpose or tool.description, "risk_level": "low", "requires_approval": bool(tool.requires_approval)})
    return tools


def validate_tool_names(names: Any, registry: dict[str, dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    """Split proposed names into (internal tools, query tools, rejected unknown names)."""
    internal, query, rejected = [], [], []
    for raw in names if isinstance(names, list) else []:
        name = str(raw).strip()
        if not name:
            continue
        entry = registry.get(name)
        if entry is None:
            rejected.append(name[:120])
        elif entry["kind"] == "tool" and name not in internal:
            internal.append(name)
        elif entry["kind"] == "query_tool" and name not in query:
            query.append(name)
    return internal, query, rejected


def _local_tool_scores(brief: str, registry: dict[str, dict[str, Any]]) -> dict[str, float]:
    wanted = _words(brief)
    scores = {}
    for name, entry in registry.items():
        overlap = len(wanted & (_words(name.replace(".", " ").replace("_", " ")) | _words(entry["description"])))
        if overlap:
            scores[name] = float(overlap)
    total = sum(scores.values())
    return {name: round(value / total, 4) for name, value in scores.items()} if total else {}


def _pick(probabilities: dict[str, float], limit: int = 4, floor: float = 0.15) -> list[str]:
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    return [name for index, (name, value) in enumerate(ranked[:limit]) if index == 0 or value >= floor]


def _jev_tool_scores(db: Session, user: User | None, name: str, brief: str, registry: dict[str, dict[str, Any]], project_id: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if user is None or len(registry) < 2:
        return None, None
    from . import jev_client
    from .provider_selection import routed_only_provider

    try:
        provider = routed_only_provider(db, user, "tool_selection")
    except Exception:
        provider = None
    if provider is None:
        return None, None
    options = {tool: entry["description"] or tool for tool, entry in registry.items()}
    return jev_client.choose_tools_with_error(db, provider, f"Bind the tools agent '{name}' needs to do its job: {brief}", f"Design the {name} agent", options, project_id, getattr(user, "id", None))


# ---------------------------------------------------------------- agents

def _template_purpose(name: str, brief: str) -> str:
    brief = (brief or "").strip()
    if brief:
        return brief[0].upper() + brief[1:] if brief[-1] in ".!?" else f"{brief[0].upper()}{brief[1:]}."
    return f"The {name} agent handles {name.lower()} requests in this project using governed, read-only tools."


def _template_instructions(name: str, purpose: str) -> str:
    return (
        f"You are the {name} specialist in DataPilot. {purpose} Ground decisions in project metadata, emit evidence, "
        "respect tool schemas, and stop when approval is required."
    )


def draft_agent(db: Session, user: User | None, project_id: str | None, name: str, brief: str) -> dict[str, Any]:
    registry = registry_tools(db, project_id)
    provider = design_provider(db, user)
    drafted: dict[str, Any] = {}
    model_error = None
    if provider is not None:
        listing = "\n".join(f"- {tool} ({entry['kind']}, risk {entry['risk_level']}): {entry['description'][:200]}" for tool, entry in registry.items())
        system = (
            "You design agents for DataPilot, a governed data platform. Reply with JSON only: "
            '{"purpose": "<one or two sentences>", "instructions": "<4-8 sentences of operating instructions>", '
            '"autonomy_level": <0 plan only | 1 low-risk tools | 2 standard | 3 extended>, "tool_names": ["<name>", ...]}. '
            "Choose tool_names ONLY from the listed tool names, copied exactly; never invent a tool. "
            "Instructions must keep deterministic approvals and read-only rules in force."
        )
        prompt = f"Agent name: {name}\nBrief: {brief}\nAvailable tools:\n{listing or '(none)'}"
        drafted, model_error = _generate(db, provider, system, prompt, 900, project_id, getattr(user, "id", None))
        drafted = drafted or {}

    jev_choice, jev_error = _jev_tool_scores(db, user, name, brief, registry, project_id)
    if jev_choice:
        # One "choice" question spreads probability across every tool, so keep all strong options
        # (>= a quarter of the top score) and add the design model's registry-valid picks: an agent needs a set.
        probabilities = jev_choice["probabilities"]
        top = max(probabilities.values(), default=0.0)
        jev_picks = _pick(probabilities, limit=4, floor=max(0.08, top * 0.25))
        model_picks = [tool for tool in (drafted.get("tool_names") or []) if isinstance(tool, str) and tool in registry]
        # The model tends to list many tools; Jev's probabilities decide which of them make the cut.
        model_picks = sorted(dict.fromkeys(model_picks), key=lambda tool: probabilities.get(tool, 0.0), reverse=True)
        proposed = list(dict.fromkeys([*jev_picks, *model_picks]))[:5]
        tool_choice = {**jev_choice, "by": "jev+llm" if set(model_picks) - set(jev_picks) else "jev", "jev_picks": jev_picks, "model_picks": model_picks}
    elif drafted.get("tool_names"):
        proposed, tool_choice = list(drafted["tool_names"]) if isinstance(drafted["tool_names"], list) else [], {"by": "llm", "model": getattr(provider, "default_model", None), "probabilities": {}}
    else:
        scores = _local_tool_scores(f"{name} {brief}", registry)
        proposed, tool_choice = _pick(scores), {"by": "local", "model": None, "probabilities": scores}
    tool_choice["error"] = jev_error
    tool_names, query_tool_names, rejected = validate_tool_names(proposed, registry)
    # Names the text model suggested are validated too, even when Jev made the final choice.
    _, _, rejected_by_model = validate_tool_names(drafted.get("tool_names"), registry)
    rejected = list(dict.fromkeys([*rejected, *rejected_by_model]))

    purpose = str(drafted.get("purpose") or "").strip()[:10_000] or _template_purpose(name, brief)
    instructions = str(drafted.get("instructions") or "").strip()[:100_000] or _template_instructions(name, purpose)
    risky = any(registry[tool]["risk_level"] != "low" or registry[tool]["requires_approval"] for tool in tool_names)
    fallback_level = 1 if risky or _CONSEQUENTIAL.search(brief or "") else 2
    try:
        autonomy_level = max(0, min(3, int(drafted.get("autonomy_level", fallback_level))))
    except (TypeError, ValueError):
        autonomy_level = fallback_level
    if risky:
        autonomy_level = min(autonomy_level, 2)
    return {
        "name": name,
        "purpose": purpose,
        "instructions": instructions,
        "autonomy_level": autonomy_level,
        "tool_names": tool_names,
        "query_tool_names": query_tool_names,
        "rejected_tool_names": rejected,
        "tool_choice": tool_choice,
        "by": "llm" if drafted else "template",
        "model": getattr(provider, "default_model", None) if drafted else None,
        "model_error": model_error,
        "saved": False,
    }


def suggest_purpose(db: Session, user: User | None, project_id: str | None, name: str, deadline: float = 8.0) -> str | None:
    """One or two sentences of purpose from an agent name, or None when no text model answers in time."""
    provider = design_provider(db, user)
    if provider is None:
        return None
    system = 'You write the purpose of a DataPilot agent from its name. Reply with JSON only: {"purpose": "<one or two sentences>"}.'
    parsed, _ = _generate(db, provider, system, f"Agent name: {name}", 200, project_id, getattr(user, "id", None), deadline=deadline)
    purpose = str((parsed or {}).get("purpose") or "").strip()
    return purpose[:10_000] or None


# ---------------------------------------------------------------- query tools

def sql_parameters(sql: str) -> list[str]:
    without_strings = re.sub(r"'(?:[^']|'')*'", "''", sql or "")
    return list(dict.fromkeys(_PARAM.findall(without_strings)))


def _parameter_type(name: str) -> str:
    lowered = name.lower()
    if lowered in {"limit", "top", "year", "month", "days"} or lowered.endswith(("_count", "_limit", "_year", "_days", "_number")):
        return "integer"
    if lowered.startswith(("min_", "max_")) or lowered.endswith(("_amount", "_rate")):
        return "number"
    if lowered.endswith(("_date", "_from", "_to", "_since", "_until")):
        return "string"
    return "string"


def _relations(sql: str) -> list[str]:
    output = []
    for raw in _RELATION.findall(sql or ""):
        relation = ".".join(part.strip('"`[] ') for part in raw.split("."))
        if relation.lower() not in {"select", "lateral"} and relation not in output:
            output.append(relation)
    return output


def _line_of_business(text: str) -> str:
    words = _words(text)
    best, best_score = "Unassigned", 0
    for label, keywords in _LINES_OF_BUSINESS:
        score = len(words & keywords)
        if score > best_score:
            best, best_score = label, score
    return best


def _tool_name(text: str, relations: list[str]) -> str:
    base = relations[0].split(".")[-1].lower() if relations else "query"
    words = [word for word in _WORD.findall((text or "").lower()) if word not in _STOP and word != base][:3]
    name = re.sub(r"[^a-z0-9_.-]", "_", f"{base}.{'_'.join(words) or 'lookup'}")
    return (name if re.match(r"^[a-z]", name) else f"q_{name}")[:120]


def draft_query_tool(db: Session, user: User | None, project_id: str | None, sql: str = "", question: str = "") -> dict[str, Any]:
    sql, question = (sql or "").strip(), (question or "").strip()
    parameters = sql_parameters(sql)
    relations = _relations(sql)
    source_text = f"{question} {sql}"
    schema: dict[str, Any] = {"type": "object", "required": parameters, "properties": {name: {"type": _parameter_type(name)} for name in parameters}, "additionalProperties": False}
    draft: dict[str, Any] = {
        "name": _tool_name(question or " ".join(relations), relations),
        "description": question or (f"Read-only query over {', '.join(relations)}." if relations else "Read-only query."),
        "purpose": question or (f"Answers questions about {', '.join(relations)}." if relations else "Governed read-only lookup."),
        "tags": list(dict.fromkeys(["read-only", "ai-drafted", *[relation.split(".")[-1].lower() for relation in relations[:3]]])),
        "parameter_schema": schema,
        "line_of_business": _line_of_business(source_text),
        "allowed_relations": relations,
        "sql_template": sql or None,
    }
    provider = design_provider(db, user)
    drafted, model_error = (None, None)
    if provider is not None:
        system = (
            "You document a governed, read-only SQL query tool for a tool registry used by agents and external clients. Reply with JSON only: "
            '{"name": "<lowercase dotted name, e.g. accounts.balance_by_type>", "description": "<one sentence>", "purpose": "<when an agent should call it>", '
            '"tags": ["<lowercase>", ...], "line_of_business": "<business area>", "parameters": {"<name>": {"type": "string|integer|number|boolean", "description": "<text>"}}}. '
            "Parameters must be exactly the :named placeholders in the SQL (none when there is no SQL)."
        )
        prompt = f"Question: {question or '(none)'}\nSQL:\n{sql[:6_000] or '(none)'}\nPlaceholders: {', '.join(parameters) or '(none)'}"
        drafted, model_error = _generate(db, provider, system, prompt, 700, project_id, getattr(user, "id", None))
    if drafted:
        name = str(drafted.get("name") or "").strip().lower()
        if re.match(r"^[a-z][a-z0-9_.-]{1,119}$", name):
            draft["name"] = name
        for field, limit in (("description", 10_000), ("purpose", 10_000), ("line_of_business", 160)):
            value = str(drafted.get(field) or "").strip()
            if value:
                draft[field] = value[:limit]
        if isinstance(drafted.get("tags"), list):
            tags = [re.sub(r"\s+", "-", str(tag).strip().lower())[:40] for tag in drafted["tags"] if str(tag).strip()]
            draft["tags"] = list(dict.fromkeys(["read-only", *tags]))[:12]
        suggested = drafted.get("parameters") if isinstance(drafted.get("parameters"), dict) else {}
        for name in parameters:  # only placeholders that really exist in the SQL
            spec = suggested.get(name) if isinstance(suggested.get(name), dict) else {}
            kind = spec.get("type") if spec.get("type") in {"string", "integer", "number", "boolean"} else schema["properties"][name]["type"]
            schema["properties"][name] = {"type": kind, **({"description": str(spec["description"])[:300]} if spec.get("description") else {})}
    existing = set(db.scalars(select(QueryTool.name).where(QueryTool.project_id == project_id)).all()) if project_id else set()
    if draft["name"] in existing:
        draft["name"] = f"{draft['name'][:112]}_v{len(existing) + 1}"
    return {**draft, "by": "llm" if drafted else "template", "model": getattr(provider, "default_model", None) if drafted else None, "model_error": model_error, "saved": False}
