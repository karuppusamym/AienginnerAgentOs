from __future__ import annotations

from datetime import timedelta

from temporalio import workflow


@workflow.defn(name="datapilot-agent-plan")
class AgentPlanWorkflow:
    @workflow.run
    async def run(self, job_id: str, objective: str) -> dict:
        return await workflow.execute_activity(
            "execute_agent_plan",
            args=[job_id, objective],
            start_to_close_timeout=timedelta(minutes=2),
        )


@workflow.defn(name="datapilot-scheduled-ingestion")
class ScheduledIngestionWorkflow:
    @workflow.run
    async def run(self, schedule_id: str, actor_id: str | None = None) -> dict:
        return await workflow.execute_activity(
            "execute_scheduled_ingestion",
            args=[schedule_id, actor_id],
            start_to_close_timeout=timedelta(minutes=10),
        )


@workflow.defn(name="datapilot-metadata-scan")
class MetadataScanWorkflow:
    @workflow.run
    async def run(self, connector_id: str, job_id: str, actor_id: str) -> dict:
        return await workflow.execute_activity(
            "execute_metadata_scan",
            args=[connector_id, job_id, actor_id],
            start_to_close_timeout=timedelta(minutes=10),
        )
