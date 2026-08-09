"""Per-connector concurrency guard for outbound connections to source databases.

Every direct-driver `execute_connector_query()` call opens a brand-new
physical DBAPI connection (pymssql/psycopg/oracledb/teradatasql) and closes
it when the query finishes -- there is no connection pooling for source-
system connectors, verified by reading `connector_runtime.py`. That shape is
reachable both from internal users (SQL workspace, query-tool test/preview)
and from external agents through the query-tool gateway
(`/external/v1/*`, `/mcp`). Under concurrent load -- several external MCP
clients, or several interactive users, querying the same connector at once
-- nothing at the DataPilot layer previously capped how many simultaneous
physical connections got opened against a single source system. The
per-client rate limiter added alongside this (`app/rate_limit.py`) bounds
*request rate* for the external gateway specifically; it does not bound
*concurrency*, and it doesn't cover internal callers at all. A burst of
slow queries within the rate-limit window, or plain concurrent internal
usage, could still open many simultaneous connections against a source
system that may have a low, hard session/connection cap of its own (common
on Oracle and Teradata in real enterprise deployments).

This module does not attempt real connection pooling -- that would need a
separate, tested implementation per driver (pymssql/psycopg/oracledb/
teradatasql all pool differently, and none of them can be validated here
against a live Oracle/Teradata/SQL Server instance). Instead it adds a much
smaller, driver-agnostic backstop: a bounded semaphore per connector_id that
caps how many physical connections DataPilot will have open against one
source system at a time, queuing briefly for a free slot before rejecting
outright rather than opening an unbounded number of connections.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator


class ConnectionLimitExceeded(RuntimeError):
    """Raised when a connector's concurrent-connection budget is exhausted."""


_lock = threading.Lock()
_semaphores: dict[str, tuple[int, threading.BoundedSemaphore]] = {}


def max_concurrent_connections() -> int:
    try:
        return max(1, int(os.getenv("CONNECTOR_MAX_CONCURRENT_CONNECTIONS", "8")))
    except ValueError:
        return 8


def _semaphore_for(connector_id: str) -> threading.BoundedSemaphore:
    limit = max_concurrent_connections()
    with _lock:
        entry = _semaphores.get(connector_id)
        if entry is None or entry[0] != limit:
            entry = (limit, threading.BoundedSemaphore(limit))
            _semaphores[connector_id] = entry
        return entry[1]


@contextmanager
def limit_connector_concurrency(connector_id: str, wait_seconds: float = 5.0) -> Iterator[None]:
    """Bound simultaneous physical connections opened against one connector.

    Waits briefly (default 5s) for a slot to free up -- a short queue is
    preferable to an outright rejection for a momentary burst of otherwise
    legitimate traffic -- then raises ConnectionLimitExceeded instead of
    opening an unbounded number of connections against the source system.
    """
    semaphore = _semaphore_for(connector_id)
    if not semaphore.acquire(timeout=wait_seconds):
        raise ConnectionLimitExceeded(
            f"Too many concurrent queries against this connector already in flight "
            f"(limit: {max_concurrent_connections()}). Try again shortly."
        )
    try:
        yield
    finally:
        semaphore.release()
