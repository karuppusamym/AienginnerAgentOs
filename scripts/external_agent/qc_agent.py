"""QA/QC for the external agent: check an answer by going back to the data.

Given an agent run (question -> tool calls -> rows -> answer with key figures),
the verifier runs three independent checks through the SAME governed MCP gateway:

  1. Grounding     - every key figure in the answer must be traceable to the rows
                     the agent received (a cell, a column sum, a row count, or a
                     per-group sum/count). Untraceable numbers = hallucination -> FAIL.
  2. Re-derivation - for each tool the agent used, call a differently shaped tool
                     (qc_rules.json: aggregate <-> detail) and recompute every
                     aggregate cell from raw rows. Disagreement -> FAIL.
  3. Reproduction  - each key figure must also be reproducible from the
                     independently fetched rows alone.

Golden set mode scores the whole agent end-to-end against known answers
(golden_set.json): answer accuracy, tool-choice accuracy, and QC pass rate.

    python qc_agent.py "How many pending payments are there?"      # agent + QC
    python qc_agent.py "What is the total deposit amount?" --inject-error answer
    python qc_agent.py --golden                                      # score golden_set.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from mcp_agent import LLM, DataPilotMCP, McpError, Printer, client_token, connect, format_table, run_agent, setting, to_number

HERE = Path(__file__).resolve().parent
RULES = json.loads((HERE / "qc_rules.json").read_text(encoding="utf-8"))


def fmt(value: float | None) -> str:
    if value is None:
        return "None"
    value = round(float(value), 6)
    return str(int(value)) if value.is_integer() else str(value)


def close(a: float, b: float, tolerance: float | None = None) -> bool:
    limit = tolerance if tolerance is not None else max(0.005, 1e-6 * abs(b))
    return abs(a - b) <= limit + 1e-9


# --------------------------------------------------------------------------- evidence -> candidate numbers

def candidates(rows: list[dict[str, Any]], origin: str) -> list[tuple[float, str]]:
    """Every number an honest answer could legitimately quote from these rows, with how it was derived."""
    found: list[tuple[float, str]] = []
    if not rows:
        return [(0.0, f"{origin}: row count")]
    columns = list(rows[0].keys())
    numeric = [column for column in columns if any(to_number(row.get(column)) is not None for row in rows)]
    text_columns = [column for column in columns if column not in numeric]
    for row_index, row in enumerate(rows):
        for column in numeric:
            value = to_number(row.get(column))
            if value is not None:
                found.append((value, f"{origin}: row {row_index + 1} {column}"))
    for column in numeric:
        found.append((sum(to_number(row.get(column)) or 0.0 for row in rows), f"{origin}: sum of {column} over all rows"))
    for group_column in text_columns:
        for group_value in {row.get(group_column) for row in rows}:
            members = [row for row in rows if row.get(group_column) == group_value]
            found.append((float(len(members)), f"{origin}: count of rows where {group_column}={group_value}"))
            for column in numeric:
                found.append((sum(to_number(row.get(column)) or 0.0 for row in members), f"{origin}: sum of {column} where {group_column}={group_value}"))
    found.append((float(len(rows)), f"{origin}: row count"))
    return found


def trace(value: float, pool: list[tuple[float, str]]) -> str | None:
    return next((how for number, how in pool if close(value, number)), None)


def numbers_in_text(text: str) -> list[float]:
    text = re.sub(r"\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?", " ", text or "")  # dates/times are not figures
    text = re.sub(r"\[[^\]]*\]", " ", text)  # [tool.names]
    values = []
    for match in re.finditer(r"(?<![\w.])-?\$?\d[\d,]*(\.\d+)?%?", text):
        token = match.group(0).replace("$", "").replace(",", "")
        if token.endswith("%"):
            continue
        number = to_number(token)
        if number is not None:
            values.append(number)
    return values


# --------------------------------------------------------------------------- re-derivation

def aggregate(expression: str, rows: list[dict[str, Any]]) -> float:
    if expression == "count":
        return float(len(rows))
    if expression.startswith("sum:"):
        column = expression[4:]
        return sum(to_number(row.get(column)) or 0.0 for row in rows)
    raise ValueError(f"unknown QC aggregate {expression}")


class Verifier:
    def __init__(self, mcp: DataPilotMCP, out: Printer) -> None:
        self.mcp = mcp
        self.out = out
        self.cache: dict[str, dict[str, Any]] = {}
        self.verify_calls: list[dict[str, Any]] = []

    def fetch(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        key = json.dumps([tool, arguments], sort_keys=True)
        if key not in self.cache:
            result = self.mcp.call_tool(tool, arguments)
            self.cache[key] = result
            self.verify_calls.append({"tool": tool, "arguments": arguments, "invocation_id": result["invocation_id"], "row_count": result["row_count"]})
            self.out.line(f"-> {tool}({json.dumps(arguments)}): {result['row_count']} row(s), invocation {result['invocation_id']}")
        return self.cache[key]

    def rederive(self, call: dict[str, Any], checks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str] | None:
        """Returns the independently fetched rows + their label (for reproduction), or None when no path is registered."""
        rule = RULES.get(call["tool"])
        if not rule:
            return None
        rows = call["result"]["rows"]
        independent: list[dict[str, Any]] = []
        if rule["mode"] == "drilldown":
            fetched: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                arguments = {argument: row.get(column) for argument, column in rule["arguments_from_row"].items()}
                detail = self.fetch(rule["verify_with"], arguments)
                fetched[detail["invocation_id"]] = detail["rows"]
                if detail.get("truncated"):
                    checks.append({"kind": "re-derivation", "status": "FAIL", "detail": f"{rule['verify_with']}({arguments}) was truncated - cannot re-derive totals from partial rows"})
                matched = [item for item in detail["rows"] if all(item.get(column) == row.get(column) for column in rule["match_columns"])]
                label = ", ".join(f"{column}={row.get(column)}" for column in rule["match_columns"])
                for column, expression in rule["compare"].items():
                    reported, derived = to_number(row.get(column)), aggregate(expression, matched)
                    ok = reported is not None and close(reported, derived)
                    checks.append({
                        "kind": "re-derivation", "status": "PASS" if ok else "FAIL",
                        "detail": f"{call['tool']} [{label}] {column}={row.get(column)} vs {expression} over {len(matched)} {rule['verify_with']} rows = {fmt(derived)}",
                    })
            for detail_rows in fetched.values():
                independent.extend(detail_rows)
            origin = f"independent {rule['verify_with']}"
        else:  # rollup: detail rows the agent got must add up to the aggregate tool
            summary = self.fetch(rule["verify_with"], rule.get("verify_arguments", {}))
            wanted = {column: call["arguments"].get(value[5:]) if str(value).startswith("$arg.") else value for column, value in rule["match"].items()}
            matched = [item for item in summary["rows"] if all(item.get(column) == value for column, value in wanted.items())]
            label = ", ".join(f"{column}={value}" for column, value in wanted.items())
            if call["result"].get("truncated"):
                checks.append({"kind": "re-derivation", "status": "FAIL", "detail": f"{call['tool']} evidence was truncated at {call['result'].get('limit')} rows - aggregates over it are unreliable"})
            for column, expression in rule["compare"].items():
                reported = sum(to_number(item.get(column)) or 0.0 for item in matched)
                derived = aggregate(expression, rows)
                ok = bool(matched) and close(reported, derived)
                checks.append({
                    "kind": "re-derivation", "status": "PASS" if ok else "FAIL",
                    "detail": f"{rule['verify_with']} [{label}] {column}={fmt(reported)} vs {expression} over the agent's {len(rows)} {call['tool']} rows = {fmt(derived)}",
                })
            independent = matched
            origin = f"independent {rule['verify_with']} [{label}]"
        return independent, origin


def inject(run: dict[str, Any], mode: str | None, out: Printer) -> None:
    """Deliberately corrupt the run to show QC catching it (demo only)."""
    if not mode:
        return
    if mode == "answer" and run["key_figures"]:
        figure = run["key_figures"][0]
        original = to_number(figure.get("value"))
        if original is not None:
            figure["value"] = round(original * 1.1 + 1, 2)
            out.line(f"!! INJECTED: answer figure '{figure.get('label')}' changed {original} -> {figure['value']} (simulated hallucination)")
    elif mode == "data":
        for call in run["calls"]:
            rule = RULES.get(call["tool"])
            rows = (call.get("result") or {}).get("rows") or []
            if rule and rows:
                # drilldown: corrupt an aggregate cell (e.g. total_amount); rollup: a detail value (e.g. amount)
                sums = [(column, expression[4:]) for column, expression in rule["compare"].items() if expression.startswith("sum:")]
                column = sums[0][0] if rule["mode"] == "drilldown" else sums[0][1]
                original = to_number(rows[0].get(column))
                if original is not None:
                    rows[0][column] = original + 7
                    out.line(f"!! INJECTED: {call['tool']} row 1 {column} changed {original} -> {original + 7} (simulated stale/buggy source tool)")
                    return


def verify_run(run: dict[str, Any], mcp: DataPilotMCP, out: Printer, inject_error: str | None = None) -> dict[str, Any]:
    out.step("QA/QC  - verify the answer against the data (independent tool calls through the same gateway)")
    inject(run, inject_error, out)
    checks: list[dict[str, Any]] = []
    succeeded = [call for call in run["calls"] if call.get("result")]
    for call in run["calls"]:
        if call.get("error"):
            checks.append({"kind": "evidence", "status": "WARN", "detail": f"{call['tool']} failed: {call['error']} - answer may be incomplete"})
    if not succeeded:
        checks.append({"kind": "evidence", "status": "FAIL", "detail": "the answer is not backed by any successful tool call"})

    # 1. grounding of each key figure in the agent's own evidence
    primary_pool = [item for call in succeeded for item in candidates(call["result"]["rows"], call["tool"])]
    figures = [(figure, to_number(figure.get("value"))) for figure in run.get("key_figures", [])]
    for figure, value in figures:
        if value is None:
            checks.append({"kind": "grounding", "status": "WARN", "detail": f"'{figure.get('label')}' has a non-numeric value {figure.get('value')!r}"})
            continue
        how = trace(value, primary_pool)
        checks.append({
            "kind": "grounding", "status": "PASS" if how else "FAIL",
            "detail": f"'{figure.get('label')}' = {fmt(value)} " + (f"<- {how}" if how else "is NOT in the tool results (no cell, sum or count matches)"),
        })
    if not figures:
        checks.append({"kind": "grounding", "status": "WARN", "detail": "the answer states no numeric key figures to verify"})
    for number in numbers_in_text(run.get("answer") or ""):
        if not trace(number, primary_pool) and not any(close(number, value) for _, value in figures if value is not None):
            checks.append({"kind": "grounding", "status": "WARN", "detail": f"number {fmt(number)} in the answer text is not traceable to the results"})

    # 2. re-derivation through differently shaped tools, 3. reproduction of each figure
    verifier = Verifier(mcp, out)
    independent_pool: list[tuple[float, str]] = []
    for call in succeeded:
        try:
            derived = verifier.rederive(call, checks)
        except McpError as exc:
            checks.append({"kind": "re-derivation", "status": "FAIL", "detail": f"verification call for {call['tool']} failed: {exc}"})
            continue
        if derived is None:
            checks.append({"kind": "re-derivation", "status": "INFO", "detail": f"no independent path registered for {call['tool']} (qc_rules.json) - grounding only"})
        else:
            independent_pool += candidates(*derived)
    if independent_pool:
        for figure, value in figures:
            if value is None:
                continue
            how = trace(value, independent_pool)
            checks.append({
                "kind": "reproduction", "status": "PASS" if how else "FAIL",
                "detail": f"'{figure.get('label')}' = {fmt(value)} " + (f"reproduced from {how}" if how else "could NOT be reproduced from the independently fetched rows"),
            })

    statuses = [check["status"] for check in checks]
    verdict = "FAIL" if "FAIL" in statuses else "PASS"
    for check in checks:
        out.line(f"{check['status']:<5} {check['kind']:<14} {check['detail']}")
    out.line("")
    out.line(f"QC VERDICT: {verdict}  ({statuses.count('PASS')} passed, {statuses.count('FAIL')} failed, {statuses.count('WARN')} warnings; {len(verifier.verify_calls)} independent tool call(s))")
    return {"verdict": verdict, "checks": checks, "verify_calls": verifier.verify_calls}


# --------------------------------------------------------------------------- golden set

def score_case(case: dict[str, Any], run: dict[str, Any]) -> tuple[bool, str]:
    expect = case["expect"]
    if "value" in expect:
        values = [to_number(figure.get("value")) for figure in run.get("key_figures", [])]
        values = [value for value in values if value is not None]
        ok = any(close(value, float(expect["value"]), float(expect.get("tolerance", 0))) for value in values)
        return ok, ", ".join(fmt(value) for value in values) or "(no figures)"
    answer = (run.get("answer") or "").lower()
    missing = [text for text in expect.get("text_contains", []) if text.lower() not in answer]
    return not missing, "missing " + ", ".join(missing) if missing else "all expected terms present"


def run_golden(path: Path, mcp: DataPilotMCP, tools: list[dict[str, Any]], llm: LLM, verbose: bool) -> int:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    quiet = Printer(enabled=verbose)
    results = []
    print(f"\nGolden set: {path.name} - {len(cases)} case(s), planner {llm.label}")
    for case in cases:
        run = run_agent(case["question"], mcp, tools, llm, quiet)
        answer_ok, got = score_case(case, run)
        used = [call["tool"] for call in run["calls"] if call.get("result")]
        tools_ok = any(tool in used for tool in case.get("expect_tools_any", used)) if case.get("expect_tools_any") else True
        qc = verify_run(run, mcp, quiet)
        results.append({"id": case["id"], "answer_ok": answer_ok, "tools_ok": tools_ok, "qc": qc["verdict"], "got": got, "used": used,
                        "expected": case["expect"].get("value", case["expect"].get("text_contains"))})
        print(f"  {'PASS' if answer_ok and qc['verdict'] == 'PASS' else 'FAIL'}  {case['id']:<24} expected {results[-1]['expected']!s:<22} got {got[:40]:<40} tools {'ok' if tools_ok else 'WRONG'} {used}  QC {qc['verdict']}")
    n = len(results)
    answers, tool_hits, qc_pass = (sum(1 for item in results if item[key] in (True, "PASS")) for key in ("answer_ok", "tools_ok", "qc"))
    print("\nScorecard")
    print(format_table(["metric", "score"], [
        {"metric": "answer accuracy (vs golden value)", "score": f"{answers}/{n} ({answers / n:.0%})"},
        {"metric": "tool-choice accuracy", "score": f"{tool_hits}/{n} ({tool_hits / n:.0%})"},
        {"metric": "QC verdict PASS (data re-derivation)", "score": f"{qc_pass}/{n} ({qc_pass / n:.0%})"},
    ], max_width=60))
    return 0 if answers == n and qc_pass == n else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="QA/QC verifier and golden-set scorer for the external agent.")
    parser.add_argument("question", nargs="?", help="run the agent on this question, then verify the answer")
    parser.add_argument("--golden", nargs="?", const=str(HERE / "golden_set.json"), metavar="PATH", help="score a golden set (default golden_set.json)")
    parser.add_argument("--inject-error", choices=["answer", "data"], help="corrupt the answer figure or the evidence to show QC failing")
    parser.add_argument("--api", default=setting("DATAPILOT_API", "http://localhost:8000"))
    parser.add_argument("--llm", choices=["auto", "gemini", "openrouter", "none"], default="auto")
    parser.add_argument("--verbose", action="store_true", help="golden mode: print every agent step")
    args = parser.parse_args()
    if not args.question and not args.golden:
        parser.error("give a question or --golden")

    print(f"DataPilot external agent QA/QC  -> {args.api}")
    out = Printer(enabled=not args.golden or args.verbose)
    mcp, tools = connect(args.api, client_token(), out)
    llm = LLM(args.llm)
    if args.golden:
        return run_golden(Path(args.golden), mcp, tools, llm, args.verbose)
    run = run_agent(args.question, mcp, tools, llm, out)
    verdict = verify_run(run, mcp, out, args.inject_error)
    return 0 if verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
