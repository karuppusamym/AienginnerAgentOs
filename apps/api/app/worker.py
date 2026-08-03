from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from .governance import initialize_governance
from .schedule_runtime import due_schedule_ids
from .temporal_activities import execute_agent_plan, execute_metadata_scan_activity, execute_scheduled_ingestion
from .temporal_runtime import TASK_QUEUE
from .temporal_workflows import AgentPlanWorkflow, MetadataScanWorkflow, ScheduledIngestionWorkflow


async def schedule_dispatch_loop(client: Client) -> None:
    while True:
        try:
            schedule_ids = await asyncio.to_thread(due_schedule_ids)
            for schedule_id in schedule_ids:
                run_key = str(int(__import__("time").time() // 60))
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
            pass
        await asyncio.sleep(15)


async def run() -> None:
    initialize_governance()
    address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    while True:
        try:
            client = await Client.connect(address)
            break
        except Exception:
            await asyncio.sleep(2)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AgentPlanWorkflow, ScheduledIngestionWorkflow, MetadataScanWorkflow],
        activities=[execute_agent_plan, execute_scheduled_ingestion, execute_metadata_scan_activity],
    )
    await asyncio.gather(worker.run(), schedule_dispatch_loop(client))


if __name__ == "__main__":
    asyncio.run(run())
