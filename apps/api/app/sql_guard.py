"""Parser-based read-only SQL validation (one module for every execution path).

The previous guard was three diverging regex blocklists; ``SELECT ... INTO``,
``WAITFOR DELAY`` and ``SHUTDOWN`` all passed. This module parses the
statement with sqlglot for the target dialect and accepts it only when:

* it is exactly one statement,
* the root is a SELECT or a set operation (UNION/INTERSECT/EXCEPT), CTEs allowed,
* it contains no write/DDL/command node, no ``SELECT ... INTO`` and no row locks,
* it calls no function from a denylist of side-effecting or file/network/sleep functions.

It also returns the referenced relations so callers can enforce that the
statement only touches catalogued tables.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

DIALECTS = {
    "postgres": "postgres",
    "sqlserver": "tsql",
    "sql_server": "tsql",
    "oracle": "oracle",
    "teradata": "teradata",
    "bigquery": "bigquery",
    "sqlite": "sqlite",
}

_WRITE_NODES = tuple(
    getattr(exp, name)
    for name in ("Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "AlterTable", "Command", "Into", "Lock", "Grant", "Revoke", "TruncateTable", "Copy", "Set", "Use", "Transaction", "Commit", "Rollback")
    if hasattr(exp, name)
)
_SET_OPERATIONS = tuple(getattr(exp, name) for name in ("Union", "Intersect", "Except") if hasattr(exp, name))

DENIED_FUNCTIONS = {
    # sleeping / resource exhaustion
    "pg_sleep", "pg_sleep_for", "pg_sleep_until", "sleep", "benchmark", "dbms_lock", "dbms_session",
    # server files, programs and network
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file", "lo_import", "lo_export", "lo_get",
    "dblink", "dblink_exec", "dblink_connect", "load_file", "xp_cmdshell", "xp_dirtree", "openrowset",
    "opendatasource", "openquery", "utl_http", "utl_file", "utl_inaddr", "dbms_pipe", "httpuritype",
    # session/state changes and arbitrary query execution
    "set_config", "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf", "query_to_xml",
    "sp_executesql", "sp_oacreate", "dbms_sql", "dbms_xmlgen", "txid_current", "nextval", "setval",
}


@dataclass(slots=True)
class GuardResult:
    ok: bool
    reason: str = ""
    relations: list[tuple[str | None, str]] = field(default_factory=list)


def _function_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name or "").lower()
    try:
        return node.sql_name().lower()
    except Exception:  # pragma: no cover - defensive for exotic nodes
        return type(node).__name__.lower()


def check_read_only(sql: str, dialect: str | None = "postgres") -> GuardResult:
    read = DIALECTS.get((dialect or "postgres").lower(), "postgres")
    try:
        statements = [statement for statement in sqlglot.parse(sql, read=read) if statement is not None]
    except Exception as exc:
        return GuardResult(False, f"SQL could not be parsed as {read}: {str(exc).splitlines()[0][:160]}")
    if len(statements) != 1:
        return GuardResult(False, "Exactly one SQL statement is allowed")
    root = statements[0]
    if not isinstance(root, (exp.Select, *_SET_OPERATIONS)):
        return GuardResult(False, f"Only SELECT statements are allowed (found {type(root).__name__})")
    for node in root.walk():
        if isinstance(node, _WRITE_NODES):
            return GuardResult(False, f"Prohibited {type(node).__name__.upper()} clause in a read-only query")
        if isinstance(node, exp.Func) and _function_name(node) in DENIED_FUNCTIONS:
            return GuardResult(False, f"Function {_function_name(node)} is not allowed in governed queries")
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    relations: list[tuple[str | None, str]] = []
    for table in root.find_all(exp.Table):
        name = str(table.name or "").lower()
        if not name or name in cte_names:
            continue
        schema = str(table.db or "").lower() or None
        relations.append((schema, name))
    return GuardResult(True, relations=relations)


def is_read_only(sql: str, dialect: str | None = None) -> bool:
    """True when the SQL is a safe single SELECT in the given dialect (or any known one)."""
    if dialect:
        return check_read_only(sql, dialect).ok
    return any(check_read_only(sql, candidate).ok for candidate in ("postgres", "sqlserver", "oracle", "bigquery"))


def unknown_relations(sql: str, dialect: str | None, allowed: set[str]) -> list[str]:
    """Relations referenced by ``sql`` that are not in ``allowed`` ("schema.table" or bare table, lowercase)."""
    result = check_read_only(sql, dialect)
    if not result.ok:
        return []
    bare = {item.split(".")[-1] for item in allowed}
    missing = []
    for schema, table in result.relations:
        qualified = f"{schema}.{table}" if schema else table
        if qualified not in allowed and not (schema is None and table in bare):
            missing.append(qualified)
    return missing
