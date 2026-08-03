from __future__ import annotations

import ast
import time
from typing import Any

from sqlalchemy.engine import Engine

from .staging import execute_read_only


ALLOWED_BUILTINS = {
    "abs": abs,
    "len": len,
    "max": max,
    "min": min,
    "round": round,
    "sorted": sorted,
    "sum": sum,
}
ALLOWED_NODES = (
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.keyword,
    ast.Subscript,
    ast.Slice,
    ast.IfExp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)


def _execute_python(source: str, variables: dict[str, Any]) -> Any:
    tree = ast.parse(source, mode="exec")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise ValueError(f"Python notebook operation is not allowed: {type(node).__name__}")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_BUILTINS
        ):
            raise ValueError("Only approved analytical functions can be called")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("Private Python names are not allowed")

    last_expression = tree.body[-1] if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    statements = tree.body[:-1] if last_expression else tree.body
    scope = {**ALLOWED_BUILTINS, **variables}
    if statements:
        exec(compile(ast.Module(body=statements, type_ignores=[]), "<notebook>", "exec"), {"__builtins__": {}}, scope)
    output = None
    if last_expression:
        output = eval(compile(ast.Expression(last_expression.value), "<notebook>", "eval"), {"__builtins__": {}}, scope)
    variables.update({key: value for key, value in scope.items() if key not in ALLOWED_BUILTINS})
    return output


def execute_notebook(engine: Engine, cells: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    variables: dict[str, Any] = {}
    outputs: list[dict[str, Any]] = []
    for index, cell in enumerate(cells):
        cell_type = str(cell.get("type", "markdown"))
        source = str(cell.get("source", ""))
        cell_id = str(cell.get("id") or f"cell-{index + 1}")
        try:
            if cell_type == "markdown":
                result: Any = {"text": source}
            elif cell_type == "sql":
                result = execute_read_only(engine, source, 500)
                variables["last_rows"] = result["rows"]
            elif cell_type == "python":
                value = _execute_python(source, variables)
                result = {"value": repr(value) if value is not None else "completed"}
            else:
                raise ValueError(f"Unsupported notebook cell type: {cell_type}")
            outputs.append({"cell_id": cell_id, "status": "succeeded", "output": result})
        except Exception as exc:
            outputs.append({"cell_id": cell_id, "status": "failed", "error": str(exc)[:2000]})
            return {
                "status": "failed",
                "outputs": outputs,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
    return {
        "status": "succeeded",
        "outputs": outputs,
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }
