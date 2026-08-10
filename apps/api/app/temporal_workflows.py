from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# Bounds activity retries so a permanently broken input (bad connector URL,
# deleted record, DNS failure, etc.) fails the job cleanly instead of the
# default unlimited-retry policy hammering the same failure forever
# (observed: hundreds of attempts against an unreachable MCP host).
# ValueError from these activities means the referenced job/connector/schedule
# row no longer exists — that is a permanent condition, so it is excluded
# from retries rather than burning attempts on it.
_DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
    non_retryable_error_types=["ValueError"],
)


@workflow.defn(name="datapilot-agent-plan")
class AgentPlanWorkflow:
    @workflow.run
    async def run(self, job_id: str, objective: str) -> dict:
        return await workflow.execute_activity(
            "execute_agent_plan",
            args=[job_id, objective],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )


@workflow.defn(name="datapilot-scheduled-ingestion")
class ScheduledIngestionWorkflow:
    @workflow.run
    async def run(self, schedule_id: str, actor_id: str | None = None) -> dict:
        return await workflow.execute_activity(
            "execute_scheduled_ingestion",
            args=[schedule_id, actor_id],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )


@workflow.defn(name="datapilot-external-extraction")
class ExternalExtractionWorkflow:
    @workflow.run
    async def run(self, extraction_id: str, actor_id: str | None = None) -> dict:
        return await workflow.execute_activity(
            "execute_external_extraction",
            args=[extraction_id, actor_id],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )


@workflow.defn(name="datapilot-metadata-scan")
class MetadataScanWorkflow:
    @workflow.run
    async def run(self, connector_id: str, job_id: str, actor_id: str) -> dict:
        return await workflow.execute_activity(
            "execute_metadata_scan",
            args=[connector_id, job_id, actor_id],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )
