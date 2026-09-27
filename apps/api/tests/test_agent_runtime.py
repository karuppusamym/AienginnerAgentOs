"""Agent runtime hardening: plan-bound approvals, autonomy enforcement and
durable per-step execution (architecture review findings H5 / H6).

Everything here drives the phase functions in app.temporal_activities
directly or through the local (no-Temporal) fallback, so no Temporal server
or test server download is needed.
"""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-agent-runtime-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("QDRANT_URL", "")
os.environ.setdefault("SUPERSET_INTERNAL_URL", "")
os.environ.setdefault("SUPERSET_ADMIN_PASSWORD", "")
os.environ.setdefault("SUPERSET_EDITOR_SSO_SECRET", "test-editor-secret")
os.environ.setdefault("ENABLE_DEMO_DATA", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import temporal_activities as runtime
from app import temporal_runtime
from app.database import SessionLocal
from app.main import app
from app.models import AgentDefinition, AgentVersion, Approval, AuditEvent, Job, ModelProvider, ProjectMembership, ToolExecution, User
from app.tool_runtime import ToolRuntimeError

SAFE_PLAN = [
    {"agent": "Planner", "action": "Decompose objective and set limits"},
    {"agent": "Metadata", "action": "Retrieve catalog and vector context"},
    {"agent": "Analytics", "action": "Explain approved metrics and result shape"},
]


def _planned(plan=None) -> dict:
    return {
        "plan": [dict(step) for step in (plan or SAFE_PLAN)],
        "trace_outputs": [{"type": "plan", "agent": "Planner", "title": "Fixed plan", "data": plan or SAFE_PLAN}],
        "logs": [],
        "source": "deterministic",
        "planning_fallback": False,
        "grounding": {"catalog_matches": 1, "vector_hits": 0, "semantic_matches": 0},
    }


def _fake_tools(db, job, plan, objective, provider=None, *, autonomy_level=2, budget=None):
    """Stand-in for _execute_bound_tools: one call, one output per step."""
    if budget is not None:
        budget["remaining"] -= 1
    step = plan[0]
    return (
        [{"type": "tool", "label": f"{step['agent']} used fake.tool", "tool": "fake.tool"}],
        [{"at": "now", "level": "info", "message": f"{step['agent']} completed fake.tool"}],
        [{"type": "tool_result", "agent": step["agent"], "tool": "fake.tool", "title": step["action"]}],
    )


class AgentRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        token = cls.client.post(
            "/auth/login", json={"email": "admin@datapilot.local", "password": "ChangeMe123!"}
        ).json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {token}"}
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.email == "admin@datapilot.local"))
            membership = db.scalar(
                select(ProjectMembership).where(ProjectMembership.user_id == admin.id, ProjectMembership.is_current.is_(True))
            )
            cls.admin_id = admin.id
            cls.project_id = membership.project_id
        cls.created_jobs: list[str] = []

    @classmethod
    def tearDownClass(cls) -> None:
        # Leave the shared test database as other suites expect it.
        with SessionLocal() as db:
            for job_id in cls.created_jobs:
                for approval in db.scalars(select(Approval).where(Approval.job_id == job_id)).all():
                    db.delete(approval)
                for execution in db.scalars(select(ToolExecution).where(ToolExecution.job_id == job_id)).all():
                    db.delete(execution)
            db.flush()
            for job_id in cls.created_jobs:
                job = db.get(Job, job_id)
                if job is not None:
                    db.delete(job)
            db.commit()
        cls.client_context.__exit__(None, None, None)

    # -- helpers ---------------------------------------------------------
    def _job(self, objective: str = "Summarize available customer data", autonomy: int = 2) -> str:
        with SessionLocal() as db:
            job = Job(
                project_id=self.project_id,
                title=objective[:200],
                job_type="agent_run",
                status="PLANNING",
                progress=5,
                plan=[],
                evidence=[runtime.agent_runtime_evidence(autonomy, objective)],
                logs=[],
                outputs=[],
                created_by=self.admin_id,
            )
            db.add(job)
            db.commit()
            self.created_jobs.append(job.id)
            return job.id

    def _load(self, job_id: str) -> Job:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            db.expunge(job)
            return job

    def _approval_for(self, job_id: str) -> Approval:
        with SessionLocal() as db:
            approval = db.scalar(select(Approval).where(Approval.job_id == job_id).order_by(Approval.created_at.desc()))
            db.expunge(approval)
            return approval

    def _start_risky_run(self, objective: str) -> dict:
        response = self.client.post("/agents/runs", headers=self.headers, json={"objective": objective, "autonomy_level": 2})
        self.assertEqual(response.status_code, 201, response.text)
        self.created_jobs.append(response.json()["job_id"])
        return response.json()

    # -- plan hash -------------------------------------------------------
    def test_plan_hash_is_canonical_and_binds_objective_and_steps(self) -> None:
        base = runtime.compute_plan_hash("Delete stale rows", SAFE_PLAN)
        decorated = [{**step, "status": "complete", "step_index": i, "extra": 1} for i, step in enumerate(SAFE_PLAN)]
        self.assertEqual(base, runtime.compute_plan_hash("Delete stale rows", decorated))
        self.assertNotEqual(base, runtime.compute_plan_hash("Delete all rows", SAFE_PLAN))
        changed = [*SAFE_PLAN[:-1], {"agent": "Analytics", "action": "Drop the table"}]
        self.assertNotEqual(base, runtime.compute_plan_hash("Delete stale rows", changed))
        self.assertNotEqual(base, runtime.compute_plan_hash("Delete stale rows", list(reversed(SAFE_PLAN))))
        self.assertEqual(len(base), 64)

    def test_risky_run_stores_plan_and_hash_in_approval(self) -> None:
        objective = "Delete the stale staging rows for customers " + "with a long rationale " * 12
        run = self._start_risky_run(objective)
        self.assertEqual(run["status"], "WAITING_FOR_APPROVAL")
        self.assertTrue(run["plan_bound"])
        approval = self._approval_for(run["job_id"])
        evidence = approval.evidence
        self.assertEqual(evidence["objective"], objective)  # full, not truncated to the 200-char title
        self.assertTrue(evidence["plan_bound"])
        self.assertGreaterEqual(len(evidence["plan"]), 3)
        self.assertEqual(evidence["plan_hash"], runtime.compute_plan_hash(objective, evidence["plan"]))
        self.assertEqual(run["plan_hash"], evidence["plan_hash"])
        job = self._load(run["job_id"])
        self.assertEqual(runtime.canonical_plan(job.plan), evidence["plan"])
        self.assertEqual(runtime._runtime(job)["plan_hash"], evidence["plan_hash"])

    # -- approval executes the frozen plan -------------------------------
    def test_approval_executes_frozen_plan_without_replanning(self) -> None:
        run = self._start_risky_run("Delete duplicate customer rows after review")
        approval = self._approval_for(run["job_id"])
        approved_plan = approval.evidence["plan"]
        with mock.patch.object(runtime, "_plan_for_job", side_effect=AssertionError("planner must not run after approval")) as planner, \
                mock.patch.object(runtime, "generate_text", side_effect=AssertionError("model must not be called")) as model:
            decision = self.client.post(
                f"/approvals/{approval.id}/decision", headers=self.headers, json={"decision": "approved", "note": "ok"}
            )
        self.assertEqual(decision.status_code, 200, decision.text)
        self.assertEqual(decision.json()["job_status"], "SUCCEEDED")
        self.assertEqual(decision.json()["plan_hash"], approval.evidence["plan_hash"])
        planner.assert_not_called()
        model.assert_not_called()
        job = self._load(run["job_id"])
        self.assertEqual(runtime.canonical_plan(job.plan), approved_plan)
        self.assertTrue(all(step["status"] == "complete" for step in job.plan))
        self.assertEqual(
            [step["idempotency_key"] for step in job.plan],
            [runtime.step_idempotency_key(job.id, i) for i in range(len(job.plan))],
        )
        self.assertTrue(any("verbatim" in entry["message"] for entry in job.logs))
        # Exactly one approval: executing the approved plan never re-holds.
        with SessionLocal() as db:
            count = len(db.scalars(select(Approval).where(Approval.job_id == job.id)).all())
        self.assertEqual(count, 1)

    def test_hash_mismatch_fails_safely_without_executing(self) -> None:
        run = self._start_risky_run("Delete orphaned account rows")
        approval = self._approval_for(run["job_id"])
        with SessionLocal() as db:
            stored = db.get(Approval, approval.id)
            tampered = dict(stored.evidence)
            tampered["plan"] = [*tampered["plan"], {"agent": "SQL Analyst", "action": "Drop the customers table"}]
            stored.evidence = tampered
            db.commit()
        with mock.patch.object(runtime, "_execute_bound_tools") as tools, \
                mock.patch.object(runtime, "_plan_for_job") as planner:
            decision = self.client.post(
                f"/approvals/{approval.id}/decision", headers=self.headers, json={"decision": "approved"}
            )
        self.assertEqual(decision.status_code, 200, decision.text)
        self.assertEqual(decision.json()["job_status"], "FAILED")
        tools.assert_not_called()
        planner.assert_not_called()
        job = self._load(run["job_id"])
        self.assertTrue(any("integrity check failed" in entry["message"] for entry in job.logs if entry["level"] == "error"))
        self.assertFalse(any(step.get("status") == "complete" for step in job.plan))

    def test_step_refuses_to_run_when_plan_was_altered(self) -> None:
        job_id = self._job()
        with mock.patch.object(runtime, "_plan_for_job", return_value=_planned()):
            self.assertEqual(runtime._prepare_agent_run(job_id, "Summarize available customer data")["status"], "READY")
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            plan = [dict(step) for step in job.plan]
            plan[1]["action"] = "Export every table to an external bucket"
            job.plan = plan
            db.commit()
        with mock.patch.object(runtime, "_execute_bound_tools") as tools:
            result = runtime._execute_agent_step(job_id, 1)
        self.assertEqual(result["status"], "FAILED")
        tools.assert_not_called()
        self.assertEqual(self._load(job_id).status, "FAILED")

    # -- reviewer-added steps --------------------------------------------
    def test_risky_reviewer_step_is_skipped_not_executed(self) -> None:
        job_id = self._job()
        reviewer = mock.Mock(side_effect=[
            [{"agent": "Quality", "action": "Delete the duplicate rows"}, {"agent": "Analytics", "action": "Summarize the cleaned result"}],
            [],
        ])
        fake_provider = SimpleNamespace(id="p1", provider_type="openai", name="Fake", default_model="fake")
        executed_actions: list[str] = []

        def tools(db, job, plan, objective, provider=None, **kwargs):
            executed_actions.append(plan[0]["action"])
            return _fake_tools(db, job, plan, objective, provider, **kwargs)

        with mock.patch.object(runtime, "_plan_for_job", return_value=_planned()), \
                mock.patch.object(runtime, "_job_provider", return_value=fake_provider), \
                mock.patch.object(runtime, "_review_plan_outputs", reviewer), \
                mock.patch.object(runtime, "_execute_bound_tools", side_effect=tools):
            result = runtime.run_agent_plan_locally(job_id, "Summarize available customer data")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertNotIn("Delete the duplicate rows", executed_actions)
        self.assertIn("Summarize the cleaned result", executed_actions)
        job = self._load(job_id)
        risky = next(step for step in job.plan if step["action"] == "Delete the duplicate rows")
        self.assertEqual(risky["status"], "skipped")
        self.assertEqual(risky["skip_reason"], "skipped: requires approval")
        self.assertEqual(risky["origin"], "reviewer")
        skipped_outputs = [item for item in job.outputs if item["type"] == "step_skipped"]
        self.assertEqual(len(skipped_outputs), 1)
        self.assertEqual(skipped_outputs[0]["summary"], "skipped: requires approval")
        self.assertTrue(any("requires approval" in item.get("label", "") for item in job.evidence))
        self.assertEqual(risky["idempotency_key"], runtime.step_idempotency_key(job_id, risky["step_index"]))
        # Re-delivering the step after the run finished is a no-op.
        with mock.patch.object(runtime, "_execute_bound_tools") as tools_again:
            self.assertEqual(runtime._execute_agent_step(job_id, risky["step_index"])["status"], "SUCCEEDED")
        tools_again.assert_not_called()

    def test_step_function_risk_checks_reviewer_steps_itself(self) -> None:
        job_id = self._job()
        with mock.patch.object(runtime, "_plan_for_job", return_value=_planned()):
            runtime._prepare_agent_run(job_id, "Summarize available customer data")
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            job.plan = [*job.plan, {"agent": "Quality", "action": "Truncate the staging table", "origin": "reviewer", "status": "pending", "step_index": len(job.plan)}]
            db.commit()
            index = len(job.plan) - 1
        with mock.patch.object(runtime, "_execute_bound_tools") as tools:
            result = runtime._execute_agent_step(job_id, index)
        self.assertEqual(result["status"], "SKIPPED")
        tools.assert_not_called()

    # -- autonomy --------------------------------------------------------
    def test_autonomy_zero_is_plan_only(self) -> None:
        with mock.patch.object(runtime, "execute_tool") as execute_tool, \
                mock.patch.object(runtime, "_execute_bound_query_tool") as query_tool:
            response = self.client.post(
                "/agents/runs", headers=self.headers,
                json={"objective": "Summarize available customer data", "autonomy_level": 0},
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.created_jobs.append(response.json()["job_id"])
            risky = self.client.post(
                "/agents/runs", headers=self.headers,
                json={"objective": "Delete the stale rows", "autonomy_level": 0},
            )
            self.created_jobs.append(risky.json()["job_id"])
        execute_tool.assert_not_called()
        query_tool.assert_not_called()
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        job = self.client.get(f"/jobs/{response.json()['job_id']}", headers=self.headers).json()
        self.assertTrue(any(item["type"] == "plan_only" for item in job["outputs"]))
        self.assertFalse(any(item["type"] in {"tool_result", "query_tool_result"} for item in job["outputs"]))
        self.assertTrue(any("plan only" in item["label"] for item in job["evidence"]))
        self.assertTrue(all(step["status"] == "planned" for step in job["plan"]))
        # Nothing executes at level 0, so there is nothing to approve.
        self.assertEqual(risky.json()["status"], "SUCCEEDED")
        self.assertIsNone(risky.json()["approval_id"])

    def test_autonomy_zero_step_function_executes_nothing(self) -> None:
        job_id = self._job(autonomy=0)
        with mock.patch.object(runtime, "_plan_for_job", return_value=_planned()):
            runtime._prepare_agent_run(job_id, "Summarize available customer data")
        with mock.patch.object(runtime, "execute_tool") as execute_tool:
            self.assertEqual(runtime._execute_agent_step(job_id, 0)["status"], "SKIPPED")
            evidence, logs, outputs = runtime._execute_bound_tools(None, self._load(job_id), SAFE_PLAN, "x", autonomy_level=0)
        execute_tool.assert_not_called()
        self.assertEqual((evidence, logs, outputs), ([], [], []))

    def test_autonomy_level_is_persisted_and_level_one_is_read_only(self) -> None:
        job = self._load(self._job(autonomy=1))
        self.assertEqual(runtime.job_autonomy_level(job), 1)
        legacy = SimpleNamespace(evidence=[{"type": "policy", "label": "Autonomy level 3"}])
        self.assertEqual(runtime.job_autonomy_level(legacy), 3)
        self.assertEqual(runtime.job_autonomy_level(SimpleNamespace(evidence=[])), 2)
        read_tool = SimpleNamespace(category="metadata", risk_level="low", requires_approval=False)
        write_tool = SimpleNamespace(category="execution", risk_level="low", requires_approval=False)
        builtin = lambda handler: SimpleNamespace(implementation_type="builtin", handler_name=handler)
        self.assertTrue(runtime._is_read_only_builtin(read_tool, builtin("catalog.search")))
        self.assertFalse(runtime._is_read_only_builtin(write_tool, builtin("catalog.search")))
        self.assertFalse(runtime._is_read_only_builtin(read_tool, builtin("sql.preview")))
        self.assertFalse(runtime._is_read_only_builtin(read_tool, builtin("pipeline.stage")))

    # -- durable per-step execution --------------------------------------
    def test_step_execution_is_idempotent(self) -> None:
        job_id = self._job()
        planner = mock.Mock(return_value=_planned())
        with mock.patch.object(runtime, "_plan_for_job", planner):
            first = runtime._prepare_agent_run(job_id, "Summarize available customer data")
            # A retried prepare (e.g. Temporal re-delivery) must not re-plan.
            second = runtime._prepare_agent_run(job_id, "Summarize available customer data")
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(first["pending_steps"], [0, 1, 2])
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        with mock.patch.object(runtime, "_execute_bound_tools", side_effect=_fake_tools) as tools:
            once = runtime._execute_agent_step(job_id, 0)
            twice = runtime._execute_agent_step(job_id, 0)
        self.assertEqual(once["status"], "COMPLETED")
        self.assertEqual(twice["status"], "ALREADY_COMPLETED")
        self.assertEqual(once["idempotency_key"], f"{job_id}:0")
        self.assertEqual(tools.call_count, 1)
        job = self._load(job_id)
        self.assertEqual(len([item for item in job.outputs if item.get("step_index") == 0]), 1)
        self.assertEqual(len([item for item in job.evidence if item.get("step_index") == 0]), 1)
        self.assertEqual(runtime._runtime(job)["tool_calls_used"], 1)
        with mock.patch.object(runtime, "_execute_bound_tools", side_effect=_fake_tools):
            for index in (1, 2):
                runtime._execute_agent_step(job_id, index)
        self.assertEqual(runtime._finalize_agent_run(job_id)["status"], "SUCCEEDED")
        self.assertEqual(runtime._finalize_agent_run(job_id)["status"], "SUCCEEDED")
        job = self._load(job_id)
        self.assertEqual(len([entry for entry in job.logs if entry["message"] == "Specialist plan completed"]), 1)
        self.assertEqual(len([item for item in job.evidence if "step_index" in item]), 3)

    def test_cancelled_job_steps_do_not_run(self) -> None:
        job_id = self._job()
        with mock.patch.object(runtime, "_plan_for_job", return_value=_planned()):
            runtime._prepare_agent_run(job_id, "Summarize available customer data")
        with SessionLocal() as db:
            db.get(Job, job_id).status = "CANCELLED"
            db.commit()
        with mock.patch.object(runtime, "_execute_bound_tools") as tools:
            self.assertEqual(runtime._execute_agent_step(job_id, 0)["status"], "CANCELLED")
        tools.assert_not_called()
        self.assertEqual(runtime._finalize_agent_run(job_id)["status"], "CANCELLED")

    # -- Temporal plumbing (no server) -----------------------------------
    def test_workflow_ids_are_deterministic_and_duplicates_rejected(self) -> None:
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError

        self.assertEqual(temporal_runtime.agent_workflow_id("j1"), "datapilot-agent-j1")
        self.assertEqual(temporal_runtime.agent_workflow_id("j1", "approval-a1"), "datapilot-agent-j1-approval-a1")
        calls: list[dict] = []

        class FakeClient:
            async def start_workflow(self, workflow, **kwargs):
                calls.append({"workflow": workflow, **kwargs})
                if len(calls) > 1:
                    raise WorkflowAlreadyStartedError(kwargs["id"], workflow)

        async def scenario():
            with mock.patch.dict(os.environ, {"TEMPORAL_ADDRESS": "temporal.test:7233"}), \
                    mock.patch.object(temporal_runtime, "get_temporal_client", mock.AsyncMock(return_value=FakeClient())):
                first = await temporal_runtime.start_agent_workflow("j1", "objective", run_key="approval-a1")
                second = await temporal_runtime.start_agent_workflow("j1", "objective", run_key="approval-a1")
            return first, second

        first, second = asyncio.run(scenario())
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["workflow"], "datapilot-agent-run")
        self.assertEqual(calls[0]["id_reuse_policy"], WorkflowIDReusePolicy.REJECT_DUPLICATE)
        with mock.patch.dict(os.environ, {"TEMPORAL_ADDRESS": ""}):
            self.assertIsNone(asyncio.run(temporal_runtime.start_agent_workflow("j1", "objective")))

    # -- tool and agent choice -------------------------------------------
    def test_step_tools_are_chosen_not_all_fired_and_jev_decides_when_routed(self) -> None:
        job_id = self._job("Profile the transactions dataset")
        step = {"agent": "Metadata", "action": "Profile the dataset columns and null rates"}
        eligible = {"catalog.search": "Search the catalog for datasets", "dataset.profile": "Profile a dataset: column types, null rates, distinct values", "lineage.query": "Upstream and downstream lineage"}
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            # No decision model routed: local word overlap chooses, and says so.
            with mock.patch.object(runtime, "_job_routed_provider", return_value=None):
                evidence, outputs = [], []
                chosen = runtime._select_step_tools(db, job, "Metadata", step, job.title, eligible, evidence, outputs)
            self.assertIn("dataset.profile", chosen)
            self.assertLess(len(chosen), len(eligible))
            self.assertEqual(outputs[0]["data"]["by"], "local")
            # Jev routed: its probabilities decide, and the choice is recorded as evidence.
            verdict = {"by": "jev", "model": "typesafe/jev-1.13", "probabilities": {"catalog.search": 0.1, "dataset.profile": 0.05, "lineage.query": 0.85}, "latency_ms": 300, "cost_usd": 0.00002}
            with mock.patch.object(runtime, "_job_routed_provider", return_value=SimpleNamespace(provider_type="jev")), \
                    mock.patch("app.jev_client.choose_tools", return_value=verdict):
                evidence, outputs = [], []
                chosen = runtime._select_step_tools(db, job, "Metadata", step, job.title, eligible, evidence, outputs)
        self.assertEqual(chosen, {"lineage.query"})
        self.assertEqual(outputs[0]["type"], "tool_choice")
        self.assertIn("jev:typesafe/jev-1.13", evidence[0]["label"])
        self.assertIsNone(runtime._select_step_tools(None, None, "X", step, "", {"only.tool": "d"}, [], []))

    def test_bare_table_name_grounds_only_when_unambiguous(self) -> None:
        from collections import Counter
        from app.models import DataAsset
        schema = {"type": "object", "required": ["asset_id"], "properties": {"asset_id": {"type": "string"}}}
        with SessionLocal() as db:
            assets = db.scalars(select(DataAsset).where(DataAsset.project_id == self.project_id)).all()
            counts = Counter(asset.table_name.lower() for asset in assets)
            unique = next(asset for asset in assets if counts[asset.table_name.lower()] == 1)
            grounded = runtime._parameters_for_tool(schema, f"Profile the {unique.table_name} dataset", db, self.project_id)
            self.assertEqual(grounded, {"asset_id": unique.id})
            self.assertIsNone(runtime._parameters_for_tool(schema, "Profile the zzz_not_a_table dataset", db, self.project_id))
            duplicated = next((name for name, count in counts.items() if count > 1), None)
            if duplicated:
                self.assertIsNone(runtime._parameters_for_tool(schema, f"Profile the {duplicated} dataset", db, self.project_id))

    def test_lead_agent_from_router_owns_a_plan_step(self) -> None:
        with SessionLocal() as db:
            job = Job(project_id=self.project_id, title="Investigate failed loads", job_type="agent_run", status="PLANNING", progress=5, plan=[],
                      evidence=[runtime.agent_runtime_evidence(2, "Investigate failed loads", "Troubleshooter")], logs=[], outputs=[], created_by=self.admin_id)
            db.add(job)
            db.commit()
            self.created_jobs.append(job.id)
            with mock.patch.object(runtime, "_job_provider", return_value=None):
                planned = runtime._plan_for_job(db, job, "Investigate failed loads")
        self.assertIn("Troubleshooter", [step["agent"] for step in planned["plan"]])

    def test_run_request_accepts_a_lead_agent(self) -> None:
        agents = self.client.get("/agents", headers=self.headers).json()
        quality = next(agent for agent in agents if agent["name"] == "Quality")
        bad = self.client.post("/agents/runs", headers=self.headers, json={"objective": "Check data quality", "autonomy_level": 0, "agent_id": "missing"})
        self.assertEqual(bad.status_code, 422)
        with mock.patch("app.routers.agents.start_agent_workflow", new=mock.AsyncMock(return_value=None)), \
                mock.patch("app.routers.agents.run_agent_plan_locally"):
            started = self.client.post("/agents/runs", headers=self.headers, json={"objective": "Check data quality of transactions", "autonomy_level": 0, "agent_id": quality["id"]})
        self.assertEqual(started.status_code, 201, started.text)
        self.created_jobs.append(started.json()["job_id"])
        job = self._load(started.json()["job_id"])
        self.assertEqual(runtime._runtime(job).get("lead_agent"), "Quality")

    def test_temporal_client_is_cached_and_reconnects(self) -> None:
        connect = mock.AsyncMock(side_effect=lambda address: SimpleNamespace(address=address))
        temporal_runtime.reset_temporal_client()

        async def scenario():
            with mock.patch("temporalio.client.Client.connect", connect):
                a = await temporal_runtime.get_temporal_client("temporal.test:7233")
                b = await temporal_runtime.get_temporal_client("temporal.test:7233")
                temporal_runtime.reset_temporal_client()
                c = await temporal_runtime.get_temporal_client("temporal.test:7233")
            return a, b, c

        try:
            a, b, c = asyncio.run(scenario())
        finally:
            temporal_runtime.reset_temporal_client()
        self.assertIs(a, b)
        self.assertIsNot(a, c)
        self.assertEqual(connect.await_count, 2)

    # -- agent configuration read at run time (section 5 items 1/2/4/5/8) ------
    def _agent(self, tool_names: list[str], autonomy: int = 2, instructions: str = "Test agent.", provider_id: str | None = None) -> str:
        """A throwaway enabled agent with one published version; removed after the test."""
        name = f"Runtime Test Agent {uuid4().hex[:8]}"
        with SessionLocal() as db:
            agent = AgentDefinition(name=name, purpose="Runtime test agent", autonomy_level=autonomy, tool_names=tool_names, policy={})
            db.add(agent)
            db.flush()
            db.add(AgentVersion(agent_id=agent.id, version=1, instructions=instructions, model_provider_id=provider_id, tool_names=tool_names, status="published", created_by=self.admin_id))
            db.commit()
            agent_id = agent.id

        def cleanup() -> None:
            with SessionLocal() as db:
                for version in db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id)).all():
                    db.delete(version)
                db.flush()
                agent_row = db.get(AgentDefinition, agent_id)
                if agent_row is not None:
                    db.delete(agent_row)
                db.commit()

        self.addCleanup(cleanup)
        return name

    def test_step_autonomy_is_narrowed_by_the_agents_registry_level(self) -> None:
        self.assertEqual(runtime._effective_autonomy(1, SimpleNamespace(autonomy_level=3)), 1)  # never widens
        self.assertEqual(runtime._effective_autonomy(2, SimpleNamespace(autonomy_level=1)), 1)
        self.assertEqual(runtime._effective_autonomy(2, SimpleNamespace(autonomy_level=None)), 2)
        name = self._agent(["catalog.search"], autonomy=0)
        job_id = self._job("Search the catalog for accounts")
        with SessionLocal() as db, mock.patch.object(runtime, "execute_tool") as execute_tool:
            job = db.get(Job, job_id)
            evidence, logs, _ = runtime._execute_bound_tools(db, job, [{"agent": name, "action": "Search the catalog"}], job.title, autonomy_level=2)
        execute_tool.assert_not_called()
        self.assertEqual(evidence, [])
        self.assertTrue(any("runs at autonomy level 0" in entry["message"] for entry in logs))

    def test_agent_version_provider_and_instructions_drive_parameter_fill(self) -> None:
        with SessionLocal() as db:
            provider = ModelProvider(name=f"Agent pinned {uuid4().hex[:6]}", provider_type="openai", default_model="gpt-test", enabled=True, status="healthy")
            db.add(provider)
            db.commit()
            provider_id = provider.id
        self.addCleanup(lambda: self._delete(ModelProvider, provider_id))  # runs after the agent cleanup (LIFO)
        instructions = "You profile governed datasets for the risk team. " + "x" * 900
        name = self._agent(["dataset.profile"], instructions=instructions, provider_id=provider_id)
        routed = SimpleNamespace(id="routed", provider_type="openai", name="Routed", default_model="routed")
        job_id = self._job("Profile something unnamed")
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            version = db.scalar(select(AgentVersion).join(AgentDefinition, AgentDefinition.id == AgentVersion.agent_id).where(AgentDefinition.name == name))
            self.assertEqual(runtime._agent_provider(db, job, version, routed).id, provider_id)
            self.assertIs(runtime._agent_provider(db, job, SimpleNamespace(model_provider_id=None), routed), routed)
            # No asset is named, so the heuristic fails and the model fill gets the agent's provider + clipped instructions.
            fill = mock.Mock(return_value=None)
            with mock.patch.object(runtime, "_llm_parameters_for_tool", fill), mock.patch.object(runtime, "execute_tool") as execute_tool:
                runtime._execute_bound_tools(db, job, [{"agent": name, "action": "Profile it"}], job.title, routed)
            execute_tool.assert_not_called()
            self.assertEqual(fill.call_args.args[1].id, provider_id)
            passed_instructions = fill.call_args.args[7]
            self.assertTrue(passed_instructions.startswith("You profile governed datasets"))
            self.assertLessEqual(len(passed_instructions), runtime.AGENT_INSTRUCTIONS_PROMPT_CHARS)
            # An unusable pinned provider falls back to the routed one.
            db.get(ModelProvider, provider_id).enabled = False
            db.flush()
            self.assertIs(runtime._agent_provider(db, job, version, routed), routed)
            db.rollback()
            # So does a local_mock pin (it cannot fill parameters or reflect).
            db.get(ModelProvider, provider_id).provider_type = "local_mock"
            db.flush()
            self.assertIs(runtime._agent_provider(db, job, version, routed), routed)
            db.rollback()
            # The instructions reach the parameter-fill system prompt as context.
            generated = mock.Mock(return_value=SimpleNamespace(content="{}", latency_ms=1))
            with mock.patch.object(runtime, "generate_text", generated):
                self.assertIsNone(runtime._llm_parameters_for_tool(db, routed, {"required": ["asset_id"], "properties": {"asset_id": {"type": "string"}}}, "x", self.project_id, "dataset.profile", job, "Only profile finance tables."))
            self.assertIn("Only profile finance tables.", generated.call_args.args[1])
            self.assertIn("cannot relax", generated.call_args.args[1])
            db.rollback()

    def _delete(self, model, row_id: str) -> None:
        with SessionLocal() as db:
            row = db.get(model, row_id)
            if row is not None:
                db.delete(row)
                db.commit()

    def test_planner_prompt_carries_agent_registry_instructions(self) -> None:
        marker = f"Marker-{uuid4().hex[:8]} owns reconciliation of ledger balances."
        name = self._agent(["catalog.search"], instructions=marker)
        job_id = self._job("Reconcile the ledger")
        plan_json = '[{"agent": "Planner", "action": "Scope"}, {"agent": "Metadata", "action": "Ground"}, {"agent": "%s", "action": "Reconcile"}]' % name
        generated = mock.Mock(return_value=SimpleNamespace(content=plan_json, latency_ms=3))
        fake = SimpleNamespace(id="p1", provider_type="openai", name="Fake", default_model="fake")
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            with mock.patch.object(runtime, "_job_provider", return_value=fake), mock.patch.object(runtime, "generate_text", generated):
                planned = runtime._plan_for_job(db, job, "Reconcile the ledger")
            db.rollback()
        self.assertEqual(planned["source"], "model")
        system_prompt = generated.call_args.args[1]
        self.assertIn(f"- {name}: {marker}", system_prompt)
        self.assertIn("never override", system_prompt)

    def test_reflection_retries_draw_from_the_tool_call_budget_and_are_audited(self) -> None:
        name = self._agent(["catalog.search"])
        job_id = self._job("Search the catalog for accounts")
        budget = {"remaining": 2}
        with SessionLocal() as db, \
                mock.patch.object(runtime, "execute_tool", side_effect=ToolRuntimeError("boom")) as execute_tool, \
                mock.patch.object(runtime, "_reflect_on_tool_error", return_value={"query": "accounts"}):
            job = db.get(Job, job_id)
            _, logs, outputs = runtime._execute_bound_tools(db, job, [{"agent": name, "action": "Search the catalog"}], job.title, budget=budget)
            db.flush()  # SessionLocal does not autoflush
            executions = [
                SimpleNamespace(status=row.status, error=row.error, created_by=row.created_by)
                for row in db.scalars(select(ToolExecution).where(ToolExecution.job_id == job_id)).all()
            ]
            db.rollback()
        # First call + one reflection retry; the second repair is refused because the budget is spent.
        self.assertEqual(execute_tool.call_count, 2)
        self.assertEqual(budget["remaining"], 0)
        self.assertTrue(any("tool-call budget exhausted" in entry["message"] for entry in logs))
        self.assertEqual(sum(1 for item in outputs if item["type"] == "tool_error"), 1)
        self.assertEqual([item.status for item in executions], ["FAILED", "FAILED"])
        self.assertTrue(all(item.error == "boom" and item.created_by == self.admin_id for item in executions))

    def test_agent_tool_calls_write_tool_execution_rows(self) -> None:
        name = self._agent(["catalog.search"])
        job_id = self._job("Search the catalog for accounts")
        result = ({"count": 3, "results": [{"name": "accounts"}]}, 1, 12)
        with mock.patch.object(runtime, "execute_tool", return_value=result):
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                evidence, _, _ = runtime._execute_bound_tools(db, job, [{"agent": name, "action": "Search the catalog"}], job.title)
                db.commit()
        with SessionLocal() as db:
            executions = db.scalars(select(ToolExecution).where(ToolExecution.job_id == job_id)).all()
        self.assertEqual(len(executions), 1)
        execution = executions[0]
        self.assertEqual(execution.status, "SUCCEEDED")
        self.assertEqual(execution.created_by, self.admin_id)
        self.assertEqual(execution.duration_ms, 12)
        self.assertEqual(execution.result.get("count"), 3)
        self.assertIn("query", execution.parameters)
        self.assertIsNotNone(execution.completed_at)
        self.assertEqual(evidence[0]["tool"], "catalog.search")
        # The registry's usage view now sees the agent's call.
        history = self.client.get("/tools/executions", headers=self.headers).json()
        self.assertTrue(any(item["id"] == execution.id and item["job_id"] == job_id for item in history))

    def test_run_time_budget_skips_remaining_steps_and_partially_succeeds(self) -> None:
        job_id = self._job()
        with mock.patch.object(runtime, "_plan_for_job", return_value=_planned()):
            runtime._prepare_agent_run(job_id, "Summarize available customer data")
        self.assertIn("started_at", runtime._runtime(self._load(job_id)))
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            runtime._set_runtime(job, started_at=(runtime.datetime.now(runtime.timezone.utc) - runtime.timedelta(seconds=301)).isoformat())
            db.commit()
        with mock.patch.dict(os.environ, {"AGENT_RUN_MAX_SECONDS": "300"}), \
                mock.patch.object(runtime, "_execute_bound_tools") as tools:
            first = runtime._execute_agent_step(job_id, 0)
            later = runtime._execute_agent_step(job_id, 2)
            self.assertEqual(runtime._review_agent_plan(job_id)["pending_steps"], [])
            final = runtime._finalize_agent_run(job_id)
        tools.assert_not_called()
        self.assertEqual(first["status"], "SKIPPED")
        self.assertEqual(later["status"], "ALREADY_COMPLETED")
        self.assertEqual(final["status"], "PARTIALLY_SUCCEEDED")
        job = self._load(job_id)
        self.assertEqual(job.status, "PARTIALLY_SUCCEEDED")
        self.assertTrue(all(step["status"] == "skipped" and step["skip_reason"] == "run time budget exceeded" for step in job.plan))
        self.assertTrue(any("Run time budget exceeded" in entry["message"] for entry in job.logs))
        self.assertTrue(any(item.get("type") == "limit" and "run time budget exceeded" in item["label"] for item in job.evidence))
        # Inside a step the loop also stops at the deadline.
        self.assertTrue(runtime._past_deadline({"deadline": runtime.datetime.now(runtime.timezone.utc) - runtime.timedelta(seconds=1)}))
        self.assertFalse(runtime._past_deadline({"remaining": 3}))

    def test_limit_label_reflects_enforced_budget(self) -> None:
        with mock.patch.dict(os.environ, {"AGENT_RUN_MAX_SECONDS": "90"}):
            self.assertEqual(runtime.agent_run_limit_label(), f"{runtime.MAX_PLAN_STEPS} plan steps / {runtime.AGENT_TOOL_CALL_BUDGET} tool calls / 90 second budget")
        with mock.patch.dict(os.environ, {"AGENT_RUN_MAX_SECONDS": "300"}):
            self.assertIn("/ 5 minute budget", runtime.agent_run_limit_label())
            run = self._start_risky_run("Delete stale staging rows for the limit label check")
            job = self.client.get(f"/jobs/{run['job_id']}", headers=self.headers).json()
            self.assertIn({"type": "limit", "label": runtime.agent_run_limit_label()}, job["evidence"])

    def test_medium_risk_tools_run_only_inside_a_human_approved_run(self) -> None:
        name = self._agent(["sql.preview", "pipeline.stage"])
        objective = "Preview SELECT 1 AS n"
        job_id = self._job(objective)
        step = {"agent": name, "action": "Preview the query"}
        preview_result = ({"row_count": 1, "rows": [{"n": 1}]}, 1, 5)
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            # Not approved: sql.preview (medium) is not eligible and never runs.
            self.assertEqual(runtime._eligible_step_tools(db, job, ["sql.preview", "pipeline.stage"], [], 2), {})
            with mock.patch.object(runtime, "execute_tool", return_value=preview_result) as execute_tool:
                runtime._execute_bound_tools(db, job, [step], objective)
            execute_tool.assert_not_called()
            approval = Approval(project_id=self.project_id, job_id=job_id, title="Approve", action_type="agent_execution", status="pending", requested_by=self.admin_id, evidence={})
            db.add(approval)
            db.flush()
            runtime._set_runtime(job, approval_id=approval.id)
            db.commit()
            # A pending approval is not an approval.
            self.assertIsNone(runtime._human_approval_id(db, job))
            approval.status = "approved"
            db.commit()
            approval_id = runtime._human_approval_id(db, job)
            self.assertEqual(approval_id, approval.id)
            # Same eligible set Jev tool selection sees; high-risk/approval-gated pipeline.stage stays out.
            self.assertEqual(set(runtime._eligible_step_tools(db, job, ["sql.preview", "pipeline.stage"], [], 2, approval_id)), {"sql.preview"})
            self.assertEqual(runtime._eligible_step_tools(db, job, ["sql.preview"], [], 1, approval_id), {})  # level 1 stays read-only
            with mock.patch.object(runtime, "execute_tool", return_value=preview_result) as execute_tool:
                runtime._execute_bound_tools(db, job, [{**step, "origin": "reviewer"}], objective)
                execute_tool.assert_not_called()  # reviewer steps were not seen by the approver
                runtime._execute_bound_tools(db, job, [step], objective, autonomy_level=1)
                execute_tool.assert_not_called()
                evidence, _, _ = runtime._execute_bound_tools(db, job, [step], objective)
            self.assertEqual(execute_tool.call_count, 1)
            self.assertEqual(execute_tool.call_args.args[2], "sql.preview")
            self.assertTrue(evidence[0]["under_approval"])
            self.assertEqual(evidence[0]["approval_id"], approval_id)
            self.assertIn("ran under approval", evidence[0]["label"])
            db.rollback()

    def test_publishing_an_agent_version_requires_a_passing_evaluation_score(self) -> None:
        created = self.client.post("/agents", headers=self.headers, json={"name": f"Publish Gate {uuid4().hex[:8]}", "purpose": "Gate test", "instructions": "v1", "tool_names": ["catalog.search"]})
        self.assertEqual(created.status_code, 201, created.text)
        agent_id = created.json()["id"]

        def cleanup() -> None:
            with SessionLocal() as db:
                for version in db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id)).all():
                    db.delete(version)
                db.flush()
                db.delete(db.get(AgentDefinition, agent_id))
                db.commit()

        self.addCleanup(cleanup)

        def set_score(version: int, score: float | None) -> None:
            with SessionLocal() as db:
                db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version == version)).evaluation_score = score
                db.commit()

        publish = lambda version, query="": self.client.post(f"/agents/{agent_id}/versions/{version}/publish{query}", headers=self.headers)
        unscored = publish(1)
        self.assertEqual(unscored.status_code, 409)
        self.assertIn("no evaluation score", unscored.json()["detail"])
        set_score(1, 50.0)  # scorecard scores are 0-100
        self.assertEqual(publish(1).status_code, 409)
        set_score(1, 90.0)
        with mock.patch.dict(os.environ, {"AGENT_PUBLISH_MIN_SCORE": "0.95"}):
            self.assertEqual(publish(1).status_code, 409)
        passed = publish(1)
        self.assertEqual(passed.status_code, 200, passed.text)
        self.assertEqual(passed.json()["status"], "published")
        second = self.client.post(f"/agents/{agent_id}/versions", headers=self.headers, json={"instructions": "v2", "tool_names": ["catalog.search"]})
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(publish(2).status_code, 409)
        # A non-admin registry writer cannot force past the gate.
        from fastapi import Depends
        from app.auth import get_current_user
        from app.database import get_db

        def as_engineer(db=Depends(get_db)):
            user = db.get(User, self.admin_id)
            db.expunge(user)
            user.role = "engineer"
            return user

        app.dependency_overrides[get_current_user] = as_engineer
        try:
            refused = publish(2, "?force=true")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        self.assertEqual(refused.status_code, 409, refused.text)
        forced = publish(2, "?force=true")  # the test user is an admin
        self.assertEqual(forced.status_code, 200, forced.text)
        with SessionLocal() as db:
            statuses = {version.version: version.status for version in db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id)).all()}
            events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == agent_id, AuditEvent.event_type == "agent.version_published").order_by(AuditEvent.created_at)).all()
        self.assertEqual(statuses, {1: "retired", 2: "published"})
        self.assertEqual([(event.details["version"], event.details["force"]) for event in events], [(1, False), (2, True)])


if __name__ == "__main__":
    unittest.main()
