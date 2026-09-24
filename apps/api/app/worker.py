from __future__ import annotations

import asyncio
import logging
import os
import time

from temporalio.client import Client
from temporalio.worker import Worker

from .governance import initialize_governance
from .schedule_runtime import due_schedule_ids
from .temporal_activities import (
    execute_agent_plan,
    execute_agent_step_activity,
    execute_external_extraction,
    execute_metadata_scan_activity,
    execute_scheduled_ingestion,
    fail_agent_run_activity,
    finalize_agent_run_activity,
    prepare_agent_run_activity,
    review_agent_plan_activity,
)
from .temporal_runtime import TASK_QUEUE, get_temporal_client
from .temporal_workflows import (
    AgentPlanWorkflow,
    AgentRunWorkflow,
    ExternalExtractionWorkflow,
    MetadataScanWorkflow,
    ScheduledIngestionWorkflow,
)

logger = logging.getLogger("datapilot.worker")


async def schedule_dispatch_loop(client: Client) -> None:
    while True:
        try:
            schedule_ids = await asyncio.to_thread(due_schedule_ids)
            for schedule_id in schedule_ids:
                run_key = str(int(time.time() // 60))
                try:
                    await client.start_workflow(
                        "datapilot-scheduled-ingestion",
                        args=[schedule_id, None],
                        id=f"datapilot-ingestion-{schedule_id}-{run_key}",
                        task_queue=TASK_QUEUE,
                    )
                except Exception as exc:
                    if "already started" not in str(exc).lower():
                        raise
        except Exception:
            # Previously a bare `except Exception: pass` with no logging call
            # anywhere in this module — if due_schedule_ids() or the Temporal
            # client started failing persistently (bad DB state, schema
            # drift, expired auth), every scheduled ingestion would silently
            # stop firing forever with zero log line, metric, or trace to
            # diagnose it from. Log it so a stuck scheduler is visible instead
            # of quietly retrying into the void every 15 seconds.
            logger.exception("Scheduled-ingestion dispatch loop failed; retrying in 15s")
        await asyncio.sleep(15)


async def run() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    initialize_governance()
    address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    while True:
        try:
            client = await get_temporal_client(address)
            break
        except Exception:
            logger.warning("Temporal not reachable at %s yet, retrying in 2s", address, exc_info=True)
            await asyncio.sleep(2)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AgentRunWorkflow, AgentPlanWorkflow, ScheduledIngestionWorkflow, MetadataScanWorkflow, ExternalExtractionWorkflow],
        activities=[
            prepare_agent_run_activity,
            execute_agent_step_activity,
            review_agent_plan_activity,
            finalize_agent_run_activity,
            fail_agent_run_activity,
            execute_agent_plan,  # legacy: drains pre-upgrade AgentPlanWorkflow runs
            execute_scheduled_ingestion,
            execute_metadata_scan_activity,
            execute_external_extraction,
        ],
    )
    await asyncio.gather(worker.run(), schedule_dispatch_loop(client))


if __name__ == "__main__":
    asyncio.run(run())
