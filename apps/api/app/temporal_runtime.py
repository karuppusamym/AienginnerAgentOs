from __future__ import annotations

import os


TASK_QUEUE = "datapilot-agent-tasks"


async def start_agent_workflow(job_id: str, objective: str) -> str | None:
    address = os.getenv("TEMPORAL_ADDRESS", "").strip()
    if not address:
        return None

    from temporalio.client import Client

    client = await Client.connect(address)
    workflow_id = f"datapilot-agent-{job_id}"
    await client.start_workflow(
        "datapilot-agent-plan",
        args=[job_id, objective],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return workflow_id


async def start_scheduled_ingestion_workflow(
    schedule_id: str,
    actor_id: str | None = None,
    run_key: str | None = None,
) -> str | None:
    address = os.getenv("TEMPORAL_ADDRESS", "").strip()
    if not address:
        return None
    from temporalio.client import Client

    client = await Client.connect(address)
    suffix = run_key or __import__("uuid").uuid4().hex
    workflow_id = f"datapilot-ingestion-{schedule_id}-{suffix}"
    await client.start_workflow(
        "datapilot-scheduled-ingestion",
        args=[schedule_id, actor_id],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return workflow_id


async def start_external_extraction_workflow(
    extraction_id: str,
    actor_id: str | None = None,
    run_key: str | None = None,
) -> str | None:
    address = os.getenv("TEMPORAL_ADDRESS", "").strip()
    if not address:
        return None
    from temporalio.client import Client

    client = await Client.connect(address)
    suffix = run_key or __import__("uuid").uuid4().hex
    workflow_id = f"datapilot-extraction-{extraction_id}-{suffix}"
    await client.start_workflow(
        "datapilot-external-extraction",
        args=[extraction_id, actor_id],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return workflow_id


async def start_metadata_scan_workflow(connector_id: str, job_id: str, actor_id: str) -> str | None:
    address = os.getenv("TEMPORAL_ADDRESS", "").strip()
    if not address:
        return None
    from temporalio.client import Client

    client = await Client.connect(address)
    workflow_id = f"datapilot-metadata-{job_id}"
    await client.start_workflow(
        "datapilot-metadata-scan",
        args=[connector_id, job_id, actor_id],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return workflow_id


async def cancel_workflow(workflow_id: str) -> bool:
    address = os.getenv("TEMPORAL_ADDRESS", "").strip()
    if not address:
        return False
    from temporalio.client import Client

    client = await Client.connect(address)
    await client.get_workflow_handle(workflow_id).cancel()
    return True
