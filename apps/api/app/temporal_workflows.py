from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

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


# Agent-run phases are individually idempotent (see temporal_activities):
# prepare never re-plans once a plan is committed/approved, each step is keyed
# by job_id+step_index and skipped if already recorded, and finalize is a
# no-op on a terminal job. That is what makes bounded retries safe here.
_PHASE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=20),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)
_STEP_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)
# Activities heartbeat every ~10 s while their blocking work runs in a thread,
# so a lost worker is detected in a minute rather than at start_to_close.
_HEARTBEAT_TIMEOUT = timedelta(seconds=60)
# Initial pass plus the Reviewer's bounded extra rounds
# (temporal_activities.MAX_REVIEW_ITERATIONS == 2).
_MAX_EXECUTION_ROUNDS = 3
AGENT_RUN_WORKFLOW = "datapilot-agent-run"


@workflow.defn(name=AGENT_RUN_WORKFLOW)
class AgentRunWorkflow:
    """Durable per-step agent run: prepare -> step* -> review -> finalize."""

    @workflow.run
    async def run(self, job_id: str, objective: str) -> dict:
        try:
            prepared = await workflow.execute_activity(
                "prepare_agent_run",
                args=[job_id, objective],
                start_to_close_timeout=timedelta(minutes=3),
                heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                retry_policy=_PHASE_RETRY_POLICY,
            )
            if prepared.get("status") != "READY":
                return prepared
            if int(prepared.get("autonomy_level", 2)) > 0:
                pending = list(prepared.get("pending_steps") or [])
                for _ in range(_MAX_EXECUTION_ROUNDS):
                    for step_index in pending:
                        result = await workflow.execute_activity(
                            "execute_agent_step",
                            args=[job_id, step_index],
                            start_to_close_timeout=timedelta(minutes=5),
                            heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                            retry_policy=_STEP_RETRY_POLICY,
                        )
                        if result.get("status") in {"FAILED", "CANCELLED", "WAITING_FOR_APPROVAL"}:
                            return result
                    review = await workflow.execute_activity(
                        "review_agent_plan",
                        args=[job_id],
                        start_to_close_timeout=timedelta(minutes=2),
                        heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                        retry_policy=_PHASE_RETRY_POLICY,
                    )
                    pending = list(review.get("pending_steps") or [])
                    if not pending:
                        break
            return await workflow.execute_activity(
                "finalize_agent_run",
                args=[job_id],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_PHASE_RETRY_POLICY,
            )
        except ActivityError as exc:
            cause = exc.cause if exc.cause is not None else exc
            await workflow.execute_activity(
                "fail_agent_run",
                args=[job_id, f"Agent run failed after bounded retries: {str(cause)[:400]}"],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_PHASE_RETRY_POLICY,
            )
            raise


@workflow.defn(name="datapilot-agent-plan")
class AgentPlanWorkflow:
    """Legacy single-activity workflow. New runs use AgentRunWorkflow; this
    stays registered (unchanged history shape) so in-flight runs can drain."""

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
