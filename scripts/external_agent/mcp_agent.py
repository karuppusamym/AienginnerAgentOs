"""A plain-Python external agent that uses DataPilot as its tool registry over MCP.

It knows nothing about DataPilot's internals: it only has a client token and the
MCP endpoint. At run time it

  1. connects:  JSON-RPC ``initialize`` (+ ``notifications/initialized``) on POST /mcp
  2. discovers: ``tools/list`` -> the published tools this client was granted
  3. plans:     an LLM picks tool(s) + arguments from the tools' JSON schemas
  4. executes:  ``tools/call`` for each planned call (governed, read-only, PII-masked)
  5. answers:   the LLM composes an answer that cites the tools/rows it used
  6. (--qc)     QA/QC re-derives the figures from the data (see qc_agent.py)

Dependencies: ``httpx`` only. The LLM is called over plain HTTP (Gemini
``generateContent`` or OpenRouter chat completions); with ``--llm none`` a small
keyword planner is used instead, so the MCP part can be shown offline.

    python mcp_agent.py --list-tools
    python mcp_agent.py "What is the total deposit amount?"
    python mcp_agent.py "How many pending payments are there?" --qc
    python mcp_agent.py "Show account 50122" --dry-run

Configuration (environment, else scripts/external_agent/.client.env, else repo .env):
  DATAPILOT_API (default http://localhost:8000), DATAPILOT_CLIENT_TOKEN,
  GEMINI_API_KEY / GEMINI_MODEL, OPENROUTER_API_KEY / OPENROUTER_MODEL.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent


def _nearest_dotenv() -> Path:
    """DATAPILOT_DOTENV if set, else the closest .env above this folder (the repo root's .env)."""
    if os.getenv("DATAPILOT_DOTENV"):
        return Path(os.environ["DATAPILOT_DOTENV"])
    for parent in HERE.parents:
        if (parent / ".env").is_file():
            return parent / ".env"
    return HERE.parent.parent / ".env"


ENV_FILES = [HERE / ".client.env", _nearest_dotenv()]
MCP_PROTOCOL_VERSION = "2025-03-26"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash"
MAX_CALLS = 4

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


# --------------------------------------------------------------------------- config

def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def setting(name: str, default: str | None = None) -> str | None:
    """Environment first, then the gitignored .client.env, then the repo .env. Values are never printed."""
    if os.getenv(name):
        return os.environ[name]
    for path in ENV_FILES:
        value = _read_env_file(path).get(name)
        if value:
            return value
    return default


# --------------------------------------------------------------------------- output

class Printer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.counter = 0

    def step(self, title: str) -> None:
        if self.enabled:
            self.counter += 1
            print(f"\n[{self.counter}] {title}")

    def line(self, text: str = "", indent: int = 4) -> None:
        if self.enabled:
            for part in str(text).splitlines() or [""]:
                print(" " * indent + part)


def format_table(columns: list[str], rows: list[dict[str, Any]], max_rows: int = 10, max_width: int = 28) -> str:
    if not rows:
        return "(no rows)"
    shown = rows[:max_rows]

    def cell(value: Any) -> str:
        text = "" if value is None else str(value)
        return text if len(text) <= max_width else text[: max_width - 3] + "..."

    widths = {column: max(len(column), *(len(cell(row.get(column))) for row in shown)) for column in columns}
    lines = [" | ".join(column.ljust(widths[column]) for column in columns), "-+-".join("-" * widths[column] for column in columns)]
    lines += [" | ".join(cell(row.get(column)).ljust(widths[column]) for column in columns) for row in shown]
    if len(rows) > max_rows:
        lines.append(f"... {len(rows) - max_rows} more row(s)")
    return "\n".join(lines)


def to_number(value: Any) -> float | None:
    """Numbers arrive as JSON numbers or as decimal strings (e.g. Postgres NUMERIC -> "1890.50")."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
        return float(value)
    return None


# --------------------------------------------------------------------------- MCP client

class McpError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class DataPilotMCP:
    """Minimal MCP client for DataPilot's streamable-HTTP endpoint (JSON-RPC over POST)."""

    def __init__(self, api: str, token: str, timeout: float = 90.0) -> None:
        self.url = api.rstrip("/") + "/mcp"
        self.http = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        self._next_id = 0
        self.server_info: dict[str, Any] = {}

    def _post(self, message: dict[str, Any]) -> httpx.Response:
        return self.http.post(self.url, json=message)

    def request(self, method: str, params: dict[str, Any] | None = None, retry_on_rate_limit: bool = True) -> dict[str, Any]:
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}
        response = self._post(message)
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            error = payload["error"]
            status = (error.get("data") or {}).get("http_status")
            if status == 429 and retry_on_rate_limit:
                time.sleep(15)  # gateway rate limit: back off once, then retry
                return self.request(method, params, retry_on_rate_limit=False)
            raise McpError(error.get("message", "MCP error"), error.get("code"), status)
        return payload["result"]

    def notify(self, method: str, params: dict[str, Any] | None = None) -> int:
        return self._post({"jsonrpc": "2.0", "method": method, "params": params or {}}).status_code

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "plain-python-external-agent", "version": "1.0.0"},
        })
        self.notify("notifications/initialized")
        self.server_info = result
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        return self.request("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise McpError(json.dumps(result.get("content"))[:500])
        structured = result.get("structuredContent")
        if structured is None:  # fall back to the text content block
            structured = json.loads(result["content"][0]["text"])
        return structured


# --------------------------------------------------------------------------- LLM

class LLM:
    """Tiny JSON-mode LLM client over plain HTTP. provider: gemini | openrouter | none."""

    def __init__(self, provider: str = "auto") -> None:
        gemini_key, openrouter_key = setting("GEMINI_API_KEY"), setting("OPENROUTER_API_KEY")
        if provider == "auto":
            provider = "gemini" if gemini_key else "openrouter" if openrouter_key else "none"
        self.provider = provider
        self._keys = {"gemini": gemini_key, "openrouter": openrouter_key}
        self.models = {
            "gemini": setting("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            "openrouter": setting("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
        }
        if provider in self._keys and not self._keys[provider]:
            raise SystemExit(f"--llm {provider} needs {provider.upper()}_API_KEY in the environment or the repo .env")
        self.http = httpx.Client(timeout=120.0)

    @property
    def label(self) -> str:
        return "keyword planner (no LLM)" if self.provider == "none" else f"{self.provider}:{self.models[self.provider]}"

    def json(self, system: str, prompt: str) -> dict[str, Any]:
        try:
            text = self._gemini(system, prompt) if self.provider == "gemini" else self._openrouter(system, prompt)
        except httpx.HTTPError as exc:
            # Gemini unavailable -> fall back to OpenRouter when a key exists (and vice versa is not needed).
            if self.provider == "gemini" and self._keys["openrouter"]:
                self.provider = "openrouter"
                text = self._openrouter(system, prompt)
            else:
                raise SystemExit(f"LLM call failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        return parse_json_object(text)

    def _gemini(self, system: str, prompt: str) -> str:
        response = self.http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.models['gemini']}:generateContent",
            headers={"x-goog-api-key": self._keys["gemini"] or ""},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
        )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)

    def _openrouter(self, system: str, prompt: str) -> str:
        response = self.http.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._keys['openrouter'] or ''}", "X-Title": "DataPilot external agent demo"},
            json={
                "model": self.models["openrouter"],
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM did not return a JSON object")
    return value


# --------------------------------------------------------------------------- planning

PLANNER_SYSTEM = """You are an external data agent. You can ONLY get data by calling the governed tools listed.
Choose the smallest set of tool calls (at most 4) that answers the question.
Arguments must match each tool's inputSchema exactly: required fields, JSON types (integer vs string) and enum values.
If a figure can be computed from one aggregate tool, prefer it over listing rows.
If no tool can answer, return an empty calls list and explain why.
Return JSON only: {"calls": [{"tool": "<name>", "arguments": {...}, "why": "<one sentence>"}], "unanswerable_reason": null}"""

COMPOSER_SYSTEM = """You answer a business question using ONLY the tool results provided (governed, read-only query results).
Rules: never invent numbers; every figure must come from a result cell or a computation over result rows that you state
(e.g. "sum of total_amount over the 3 settled rows"). Masked values (like A***) must stay masked.
Return JSON only:
{"answer": "<2-4 sentence answer, cite tool names in [brackets]>",
 "key_figures": [{"label": "<what it is>", "value": <number>, "tool": "<tool name>", "derivation": "<cell | sum of col over rows ... | count of rows ... | ...>"}],
 "confidence": "high|medium|low"}
Put the numeric answer(s) to the question in key_figures (numbers only, no units)."""


def tool_catalog(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = []
    for tool in tools:
        registry = (tool.get("_meta") or {}).get("com.datapilot.registry", {})
        catalog.append({
            "name": tool["name"],
            "description": tool.get("description"),
            "purpose": tool.get("title") or registry.get("purpose"),
            "data_source": registry.get("data_source"),
            "inputSchema": tool.get("inputSchema"),
        })
    return catalog


def keyword_plan(question: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Offline fallback planner (--llm none): crude keyword routing, enough to show the MCP flow."""
    names = {tool["name"] for tool in tools}
    q = question.lower()
    number = re.search(r"\b(\d{1,9})\b", q)
    calls: list[dict[str, Any]] = []

    def add(name: str, arguments: dict[str, Any], why: str) -> None:
        if name in names:
            calls.append({"tool": name, "arguments": arguments, "why": why})

    if "account" in q and number:
        add("banking.account_lookup", {"account_id": int(number.group(1))}, "question names an account id")
    elif "customer" in q and number:
        add("commerce.customer_orders", {"customer_id": int(number.group(1))}, "question names a customer id")
    elif "payment" in q:
        add("commerce.payments_summary", {}, "payments question -> payment summary by status/method")
    elif "transaction" in q or any(word in q for word in ("deposit", "debit", "withdrawal")):
        add("banking.txn_totals_by_type", {}, "transactions question -> totals by type")
    return {"calls": calls, "unanswerable_reason": None if calls else "no keyword matched a tool"}


def plan_calls(llm: LLM, question: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    if llm.provider == "none":
        return keyword_plan(question, tools)
    prompt = f"Question: {question}\n\nAvailable tools (JSON):\n{json.dumps(tool_catalog(tools), indent=1)}"
    plan = llm.json(PLANNER_SYSTEM, prompt)
    plan["calls"] = [call for call in plan.get("calls", []) if isinstance(call, dict) and call.get("tool")][:MAX_CALLS]
    return plan


def compose_answer(llm: LLM, question: str, executed: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = [
        {
            "tool": call["tool"],
            "arguments": call["arguments"],
            "invocation_id": call.get("result", {}).get("invocation_id"),
            "columns": call.get("result", {}).get("columns"),
            "rows": call.get("result", {}).get("rows", [])[:200],
            "row_count": call.get("result", {}).get("row_count"),
            "truncated": call.get("result", {}).get("truncated"),
            "error": call.get("error"),
        }
        for call in executed
    ]
    if llm.provider == "none":
        parts = [f"[{item['tool']}] returned {item['row_count']} row(s)" for item in evidence if not item["error"]]
        return {"answer": "; ".join(parts) or "No data returned.", "key_figures": [], "confidence": "low"}
    prompt = f"Question: {question}\n\nTool results (JSON):\n{json.dumps(evidence, indent=1, default=str)}"
    return llm.json(COMPOSER_SYSTEM, prompt)


# --------------------------------------------------------------------------- the agent loop

def connect(api: str, token: str, out: Printer) -> tuple[DataPilotMCP, list[dict[str, Any]]]:
    mcp = DataPilotMCP(api, token)
    out.step(f"Connect  POST {mcp.url}  (JSON-RPC initialize, bearer client token)")
    info = mcp.initialize()
    server = info.get("serverInfo", {})
    out.line(f"server: {server.get('name')} {server.get('version')} | protocol {info.get('protocolVersion')} | capabilities {json.dumps(info.get('capabilities'))}")
    out.step("Discover  tools/list  (only published tools granted to this client are visible)")
    tools = mcp.list_tools()
    out.line(f"{len(tools)} tool(s):")
    for tool in tools:
        schema = tool.get("inputSchema") or {}
        params = ", ".join(
            f"{name}:{spec.get('type')}" + (f"{spec['enum']}" if "enum" in spec else "") + ("*" if name in schema.get("required", []) else "")
            for name, spec in (schema.get("properties") or {}).items()
        ) or "-"
        source = (tool.get("_meta") or {}).get("com.datapilot.registry", {}).get("data_source", "")
        out.line(f"- {tool['name']:<30} ({params})  [{source}]")
    return mcp, tools


def run_agent(
    question: str,
    mcp: DataPilotMCP,
    tools: list[dict[str, Any]],
    llm: LLM,
    out: Printer,
    dry_run: bool = False,
) -> dict[str, Any]:
    out.step(f"Plan  ({llm.label}) - choose tools + arguments from the schemas")
    out.line(f'question: "{question}"')
    plan = plan_calls(llm, question, tools)
    known = {tool["name"] for tool in tools}
    for index, call in enumerate(plan["calls"], 1):
        call.setdefault("arguments", {})
        flag = "" if call["tool"] in known else "   <-- not in the registry, will be refused"
        out.line(f"{index}. {call['tool']}({json.dumps(call['arguments'])}){flag}")
        out.line(f"   why: {call.get('why', '-')}")
    if not plan["calls"]:
        out.line(f"no tool call planned: {plan.get('unanswerable_reason')}")
    run: dict[str, Any] = {"question": question, "llm": llm.label, "plan": plan, "calls": [], "answer": None, "key_figures": []}
    if dry_run:
        out.step("Dry run  - JSON-RPC requests that would be sent (nothing executed)")
        for call in plan["calls"]:
            out.line(json.dumps({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": call["tool"], "arguments": call["arguments"]}}))
        return run

    out.step("Execute  tools/call  (DataPilot validates args, runs read-only SQL, masks PII, audits)")
    for call in plan["calls"]:
        executed = {"tool": call["tool"], "arguments": call["arguments"], "why": call.get("why")}
        try:
            result = mcp.call_tool(call["tool"], call["arguments"])
            executed["result"] = result
            protected = result.get("protected_columns") or []
            out.line(f"-> {call['tool']}: {result['row_count']} row(s) in {result.get('duration_ms', '?')} ms, invocation {result['invocation_id']}"
                     + (f", masked columns {protected}" if protected else "") + (" (TRUNCATED)" if result.get("truncated") else ""))
            out.line(format_table(result["columns"], result["rows"]), indent=7)
        except McpError as exc:
            executed["error"] = f"{exc} (http {exc.http_status})"
            out.line(f"-> {call['tool']}: REFUSED/FAILED - {exc} (gateway HTTP {exc.http_status})")
        run["calls"].append(executed)

    out.step("Answer  (LLM composes from the returned rows only)")
    composed = compose_answer(llm, question, run["calls"])
    run["answer"] = composed.get("answer")
    run["key_figures"] = [figure for figure in composed.get("key_figures", []) if isinstance(figure, dict)]
    run["confidence"] = composed.get("confidence")
    out.line(run["answer"])
    if run["key_figures"]:
        out.line("")
        out.line("evidence:")
        invocations = {call["tool"]: call.get("result", {}).get("invocation_id") for call in run["calls"]}
        for figure in run["key_figures"]:
            out.line(f"- {figure.get('label')}: {figure.get('value')}  <- {figure.get('tool')} ({figure.get('derivation')}); invocation {invocations.get(figure.get('tool'), '?')}")
    out.line(f"confidence: {run.get('confidence')}")
    return run


def client_token() -> str:
    token = setting("DATAPILOT_CLIENT_TOKEN")
    if not token:
        raise SystemExit("No DATAPILOT_CLIENT_TOKEN. Run: python scripts/external_agent/setup_demo_gateway.py")
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plain-Python external agent using DataPilot's MCP tool registry.")
    parser.add_argument("question", nargs="?", help="business question to answer")
    parser.add_argument("--api", default=setting("DATAPILOT_API", "http://localhost:8000"))
    parser.add_argument("--llm", choices=["auto", "gemini", "openrouter", "none"], default="auto")
    parser.add_argument("--list-tools", action="store_true", help="connect, list the granted tools with full schemas, and exit")
    parser.add_argument("--dry-run", action="store_true", help="plan only; print the tools/call requests without executing them")
    parser.add_argument("--qc", action="store_true", help="after answering, run the QA/QC verifier (qc_agent.py)")
    parser.add_argument("--json", metavar="PATH", help="also write the run (plan, calls, answer, QC) as JSON")
    parser.add_argument("--call", nargs=2, metavar=("TOOL", "ARGS_JSON"), help="skip the LLM: call one tool directly (shows gateway refusals too)")
    args = parser.parse_args(argv)
    if not args.list_tools and not args.question and not args.call:
        parser.error("a question is required (or --list-tools / --call)")

    out = Printer()
    print(f"DataPilot external agent (plain Python, MCP)  -> {args.api}")
    mcp, tools = connect(args.api, client_token(), out)
    if args.call:
        name, raw = args.call
        out.step(f"tools/call {name} {raw}")
        try:
            result = mcp.call_tool(name, json.loads(raw))
        except McpError as exc:
            out.line(f"REFUSED by the gateway: {exc} (JSON-RPC {exc.code}, HTTP {exc.http_status})")
            return 1
        out.line(f"{result['row_count']} row(s), invocation {result['invocation_id']}")
        out.line(format_table(result["columns"], result["rows"]))
        return 0
    if args.list_tools:
        out.step("Tool schemas")
        for tool in tools:
            out.line(f"{tool['name']}: {tool.get('description')}")
            out.line(f"inputSchema: {json.dumps(tool.get('inputSchema'))}", indent=6)
            out.line(f"registry: {json.dumps((tool.get('_meta') or {}).get('com.datapilot.registry'))}", indent=6)
        return 0

    llm = LLM(args.llm)
    if args.llm == "auto" and llm.provider == "none":
        print("    (no GEMINI_API_KEY / OPENROUTER_API_KEY found - using the offline keyword planner)")
    run = run_agent(args.question, mcp, tools, llm, out, dry_run=args.dry_run)
    verdict = None
    if args.qc and not args.dry_run:
        import qc_agent  # sibling module; imported lazily so the agent has no hard dependency on it

        verdict = qc_agent.verify_run(run, mcp, out)
        run["qc"] = verdict
    if args.json:
        Path(args.json).write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
        print(f"\nrun written to {args.json}")
    return 1 if verdict and verdict["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
