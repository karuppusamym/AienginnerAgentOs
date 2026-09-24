from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Awaitable, Callable


TASK_QUEUE = "datapilot-agent-tasks"
AGENT_RUN_WORKFLOW = "datapilot-agent-run"

logger = logging.getLogger("datapilot.temporal")

# One Temporal client per process (per event loop, which in the API and the
# worker is a single loop). Client.connect opens a gRPC channel; doing it on
# every call, as before, leaked channels and added a handshake to each start.
_client_state: dict[str, Any] = {"client": None, "address": None, "loop": None}
_client_lock: asyncio.Lock | None = None
_client_lock_loop: asyncio.AbstractEventLoop | None = None


def _temporal_address() -> str:
    return os.getenv("TEMPORAL_ADDRESS", "").strip()


def _lock_for(loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    global _client_lock, _client_lock_loop
    if _client_lock is None or _client_lock_loop is not loop:
        _client_lock = asyncio.Lock()
        _client_lock_loop = loop
    return _client_lock


async def get_temporal_client(address: str | None = None):
    """Return the cached client, connecting (or reconnecting) when needed."""
    from temporalio.client import Client

    address = address or _temporal_address()
    loop = asyncio.get_running_loop()
    state = _client_state
    if state["client"] is not None and state["address"] == address and state["loop"] is loop and not loop.is_closed():
        return state["client"]
    async with _lock_for(loop):
        if state["client"] is not None and state["address"] == address and state["loop"] is loop:
            return state["client"]
        client = await Client.connect(address)
        state.update(client=client, address=address, loop=loop)
        return client


def reset_temporal_client() -> None:
    """Drop the cached client so the next call reconnects."""
    _client_state.update(client=None, address=None, loop=None)


def _is_permanent_error(exc: BaseException) -> bool:
    """Errors a reconnect cannot fix (duplicates, bad requests)."""
    try:
        from temporalio.exceptions import WorkflowAlreadyStartedError
        from temporalio.service import RPCError, RPCStatusCode
    except ModuleNotFoundError:  # pragma: no cover - temporalio is a hard dependency
        return False
    if isinstance(exc, WorkflowAlreadyStartedError):
        return True
    if isinstance(exc, RPCError):
        return exc.status not in {RPCStatusCode.UNAVAILABLE, RPCStatusCode.UNKNOWN, RPCStatusCode.DEADLINE_EXCEEDED}
    return False


async def _with_client(operation: Callable[[Any], Awaitable[Any]]) -> Any:
    address = _temporal_address()
    client = await get_temporal_client(address)
    try:
        return await operation(client)
    except Exception as exc:
        if _is_permanent_error(exc):
            raise
        # Likely a dropped connection: reconnect once and retry. Workflow IDs
        # are deterministic and duplicates are rejected, so a start that did
        # reach the server before the failure cannot run twice.
        logger.warning("Temporal call failed (%s); reconnecting once", type(exc).__name__)
        reset_temporal_client()
        client = await get_temporal_client(address)
        return await operation(client)


def agent_workflow_id(job_id: str, run_key: str | None = None) -> str:
    """Deterministic per job, and per approval restart via run_key."""
    return f"datapilot-agent-{job_id}" + (f"-{run_key}" if run_key else "")


async def _start_unique(workflow: str, args: list, workflow_id: str) -> str:
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    async def start(client):
        await client.start_workflow(
            workflow,
            args=args,
            id=workflow_id,
            task_queue=TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )

    try:
        await _with_client(start)
    except WorkflowAlreadyStartedError:
        # Duplicate start (double click, client retry): the existing run is
        # authoritative; never start a second execution of the same job.
        logger.info("Workflow %s already started; duplicate start rejected", workflow_id)
    return workflow_id


async def start_agent_workflow(job_id: str, objective: str, run_key: str | None = None) -> str | None:
    if not _temporal_address():
        return None
    return await _start_unique(AGENT_RUN_WORKFLOW, [job_id, objective], agent_workflow_id(job_id, run_key))


async def start_scheduled_ingestion_workflow(
    schedule_id: str,
    actor_id: str | None = None,
    run_key: str | None = None,
) -> str | None:
    if not _temporal_address():
        return None
    suffix = run_key or uuid.uuid4().hex
    workflow_id = f"datapilot-ingestion-{schedule_id}-{suffix}"

    async def start(client):
        await client.start_workflow(
            "datapilot-scheduled-ingestion",
            args=[schedule_id, actor_id],
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )

    await _with_client(start)
    return workflow_id


async def start_external_extraction_workflow(
    extraction_id: str,
    actor_id: str | None = None,
    run_key: str | None = None,
) -> str | None:
    if not _temporal_address():
        return None
    suffix = run_key or uuid.uuid4().hex
    workflow_id = f"datapilot-extraction-{extraction_id}-{suffix}"

    async def start(client):
        await client.start_workflow(
            "datapilot-external-extraction",
            args=[extraction_id, actor_id],
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )

    await _with_client(start)
    return workflow_id


async def start_metadata_scan_workflow(connector_id: str, job_id: str, actor_id: str) -> str | None:
    if not _temporal_address():
        return None
    workflow_id = f"datapilot-metadata-{job_id}"

    async def start(client):
        await client.start_workflow(
            "datapilot-metadata-scan",
            args=[connector_id, job_id, actor_id],
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )

    await _with_client(start)
    return workflow_id


async def cancel_workflow(workflow_id: str) -> bool:
    if not _temporal_address():
        return False

    async def cancel(client):
        await client.get_workflow_handle(workflow_id).cancel()

    await _with_client(cancel)
    return True
