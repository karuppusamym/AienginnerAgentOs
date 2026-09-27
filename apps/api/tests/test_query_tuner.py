"""Plan-guided SQL tuner (app/query_tuner.py): equivalence gate, timing, early stop, guard, endpoints, approval."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-tuner-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("QDRANT_URL", "")
os.environ.setdefault("SUPERSET_INTERNAL_URL", "")
os.environ.setdefault("SUPERSET_ADMIN_PASSWORD", "")
os.environ.setdefault("SUPERSET_EDITOR_SSO_SECRET", "test-editor-secret")
os.environ.setdefault("ENABLE_DEMO_DATA", "true")
os.environ["DECISION_ROUTER_BACKEND"] = "local"

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import learning, query_tuner
from app.database import SessionLocal, engine
from app.main import app
from app.model_runtime import ProviderGenerationResult
from app.models import Approval, Job, ModelProvider, Project, QueryRun, User, VerifiedQuery

# The original reads accounts twice (IN-subquery); the fast rewrite filters once.
ORIGINAL = "SELECT a.account_type, COUNT(*) AS n FROM core.accounts a WHERE a.account_id IN (SELECT b.account_id FROM core.accounts b WHERE b.status = 'active') GROUP BY a.account_type"
FAST = "SELECT account_type, COUNT(*) AS n FROM core.accounts WHERE status = 'active' GROUP BY account_type"
FAST_TOO = "SELECT account_type, COUNT(account_id) AS n FROM core.accounts WHERE status = 'active' GROUP BY account_type"
WRONG = "SELECT account_type, COUNT(*) AS n FROM core.accounts GROUP BY account_type"  # counts the inactive account too
SIMULATED_MS = {FAST: 40.0, FAST_TOO: 39.0}


def fake_timed(self, sql, limit):
    """Deterministic timings: the real query still runs (so equivalence is real), the clock is simulated."""
    return self.run(sql, limit), SIMULATED_MS.get(sql.strip(), 100.0)


def replies(*sqls):
    return [ProviderGenerationResult(content=f'{{"sql": "{sql}", "notes": "rewrite {index}"}}', latency_ms=1) for index, sql in enumerate(sqls)]


def fake_provider() -> ModelProvider:
    return ModelProvider(name="Fake tuner", provider_type="openai_compatible", default_model="fake", enabled=True)


def project_id() -> str:
    with SessionLocal() as db:
        return db.scalar(select(Project.id).where(Project.slug == "retail-banking"))


class TunerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)  # runs startup: demo data + seeded catalog
        cls.client = cls.client_context.__enter__()
        token = cls.client.post("/auth/login", json={"email": "admin@datapilot.local", "password": "ChangeMe123!"}).json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)

    def tune(self, sql: str, model_replies: list, iterations: int = 6):
        with SessionLocal() as db, mock.patch.object(query_tuner.LocalExecutor, "timed", fake_timed), mock.patch("app.query_tuner.generate_text", side_effect=model_replies) as generate:
            report = query_tuner.tune_query(db, engine, sql, "postgres", "Active accounts by type", iterations, fake_provider(), project_id=project_id())
        return report, generate


class TuneQueryTests(TunerTestCase):
    def test_wrong_rewrite_is_rejected_and_faster_equivalent_rewrite_wins(self) -> None:
        report, generate = self.tune(ORIGINAL, replies(WRONG, FAST, FAST, FAST_TOO), iterations=6)
        attempts = report["attempts"]
        self.assertFalse(attempts[0]["equivalent"])
        self.assertIn("not equivalent", attempts[0]["rejected_reason"])
        self.assertIsNone(attempts[0]["ms"])  # rejected candidates are never timed
        self.assertTrue(attempts[1]["equivalent"] and attempts[1]["improved"])
        self.assertEqual(report["status"], "improved")
        self.assertEqual(report["winning_sql"], FAST)
        self.assertEqual((report["baseline_ms"], report["best_ms"], report["speedup_pct"]), (100.0, 40.0, 60.0))
        self.assertIn("duplicate", attempts[2]["rejected_reason"])
        # 39 ms is not 5 % better than 40 ms: second stale round in a row stops the loop.
        self.assertIn("improvement threshold", attempts[3]["rejected_reason"])
        self.assertEqual(generate.call_count, 4)
        self.assertIn("no improvement", report["stopped_reason"])
        self.assertEqual(report["baseline"]["row_count"], 2)
        self.assertNotIn("rows", report["baseline"])  # the report never stores result rows
        self.assertEqual(report["plan_support"], "query_plan")
        self.assertTrue(report["baseline"]["plan_summary"]["nodes"])

    def test_feedback_includes_previous_attempts_and_plan(self) -> None:
        _report, generate = self.tune(ORIGINAL, replies(WRONG, WRONG + " "), iterations=2)
        second_prompt = generate.call_args_list[1].args[2]
        self.assertIn("not equivalent", second_prompt)
        self.assertIn("<plan>", second_prompt)
        self.assertIn("core.accounts", second_prompt.split("<catalog>")[1])

    def test_stops_early_after_two_rounds_without_improvement(self) -> None:
        slow_equivalent = "SELECT a.account_type, COUNT(*) AS n FROM core.accounts a WHERE EXISTS (SELECT 1 FROM core.accounts b WHERE b.account_id = a.account_id AND b.status = 'active') GROUP BY a.account_type"
        report, generate = self.tune(ORIGINAL, replies(slow_equivalent, WRONG, FAST, FAST), iterations=6)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(report["status"], "no_improvement")
        self.assertTrue(report["attempts"][0]["equivalent"])
        self.assertIn("not faster", report["attempts"][0]["rejected_reason"])
        self.assertIsNone(report["winning_sql"])

    def test_guard_rejects_ddl_dml_and_foreign_tables(self) -> None:
        report, _ = self.tune(ORIGINAL, replies("DELETE FROM core.accounts", "SELECT * INTO copy_accounts FROM core.accounts", FAST), iterations=3)
        self.assertIn("guard", report["attempts"][0]["rejected_reason"])
        self.assertFalse(report["attempts"][0]["equivalent"])
        self.assertIn("guard", report["attempts"][1]["rejected_reason"])
        allowed = {"core.accounts", "core.customers"}
        self.assertIn("guard", query_tuner.guard_candidate("DROP TABLE core.accounts", "postgres", allowed))
        self.assertIn("guard", query_tuner.guard_candidate("UPDATE core.accounts SET status = 'x'", "postgres", allowed))
        self.assertIn("outside the catalog", query_tuner.guard_candidate("SELECT * FROM users", "postgres", allowed))
        self.assertIn("does not", query_tuner.guard_candidate("SELECT * FROM core.customers", "postgres", allowed, {"accounts"}))
        self.assertIn("change results", query_tuner.guard_candidate("SELECT * FROM core.accounts WITH (NOLOCK)", "sqlserver", allowed))
        with SessionLocal() as db, self.assertRaises(query_tuner.TuningError):
            query_tuner.tune_query(db, engine, "DELETE FROM core.accounts", "postgres", None, 2, fake_provider(), project_id=project_id())
        with SessionLocal() as db, self.assertRaises(query_tuner.TuningError):
            query_tuner.tune_query(db, engine, ORIGINAL, "postgres", None, 2, ModelProvider(name="local", provider_type="local_mock"), project_id=project_id())

    def test_ordered_originals_compare_row_order(self) -> None:
        ordered = "SELECT account_type, COUNT(*) AS n FROM core.accounts WHERE status = 'active' GROUP BY account_type ORDER BY account_type"
        reversed_order = "SELECT account_type, COUNT(*) AS n FROM core.accounts WHERE status = 'active' GROUP BY account_type ORDER BY account_type DESC"
        report, _ = self.tune(ordered, replies(reversed_order, reversed_order + " "), iterations=2)
        self.assertTrue(report["order_sensitive"])
        self.assertIn("different order", report["attempts"][0]["rejected_reason"])

    def test_compare_results_rules(self) -> None:
        reference = {"columns": ["t", "n"], "rows": [{"t": "a", "n": 1}, {"t": "b", "n": 2}], "row_count": 2, "truncated": False}
        shuffled = {**reference, "rows": list(reversed(reference["rows"]))}
        self.assertEqual(query_tuner.compare_results(reference, shuffled, ordered=False), (True, None))
        self.assertFalse(query_tuner.compare_results(reference, shuffled, ordered=True)[0])
        extra = {"columns": ["t", "n", "x"], "rows": [{"t": "a", "n": 1, "x": 0}, {"t": "b", "n": 2, "x": 0}], "row_count": 2, "truncated": False}
        self.assertIn("columns", query_tuner.compare_results(reference, extra, ordered=False)[1])
        numeric = {**reference, "rows": [{"t": "a", "n": 1.0}, {"t": "b", "n": 2.0}]}
        self.assertTrue(query_tuner.compare_results(reference, numeric, ordered=False)[0])


class PlanSummaryTests(unittest.TestCase):
    def test_postgres_plan_flags_seq_scans_spills_and_subplans(self) -> None:
        plan = [{"Plan": {"Node Type": "Sort", "Total Cost": 900.0, "Plan Rows": 10, "Actual Rows": 10, "Actual Loops": 1, "Actual Total Time": 50.0,
                          "Sort Space Type": "Disk", "Sort Space Used": 2048, "Sort Method": "external merge",
                          "Plans": [{"Node Type": "Seq Scan", "Relation Name": "transactions", "Total Cost": 800.0, "Plan Rows": 100, "Actual Rows": 50_000, "Actual Loops": 1,
                                     "Actual Total Time": 40.0, "Rows Removed by Filter": 150_000,
                                     "Plans": [{"Node Type": "Index Scan", "Parent Relationship": "SubPlan", "Subplan Name": "SubPlan 1", "Relation Name": "accounts", "Total Cost": 1.0,
                                                "Plan Rows": 1, "Actual Rows": 1, "Actual Loops": 5_000, "Actual Total Time": 0.004}]}]},
                 "Execution Time": 51.2, "Planning Time": 0.3}]
        summary = query_tuner.summarize_postgres_plan(plan)
        flags = " | ".join(summary["flags"])
        self.assertIn("Seq Scan on transactions", flags)
        self.assertIn("Sort spills to disk", flags)
        self.assertIn("executed 5000 times", flags)
        self.assertIn("misestimate", flags)
        self.assertEqual(summary["execution_ms"], 51.2)
        after = query_tuner.summarize_postgres_plan([{"Plan": {"Node Type": "Hash Join", "Total Cost": 100.0, "Plan Rows": 10, "Actual Rows": 10, "Actual Loops": 1, "Actual Total Time": 5.0}, "Execution Time": 5.1}])
        diff = query_tuner.plan_diff(summary, after)
        self.assertTrue(any("900.0 → 100.0" in line for line in diff))
        self.assertTrue(any(line.startswith("Resolved: Sort spills") for line in diff))

    def test_sqlserver_showplan_is_summarised(self) -> None:
        xml = (
            '<ShowPlanXML xmlns="http://schemas.microsoft.com/sqlserver/2004/07/showplan"><BatchSequence><Batch><Statements>'
            '<StmtSimple StatementSubTreeCost="12.5"><QueryPlan><MissingIndexes/>'
            '<RelOp PhysicalOp="Nested Loops" LogicalOp="Inner Join" EstimateRows="10" EstimatedTotalSubtreeCost="12.5"><NestedLoops>'
            '<RelOp PhysicalOp="Clustered Index Scan" LogicalOp="Clustered Index Scan" EstimateRows="50000" TableCardinality="50000" EstimatedTotalSubtreeCost="4.0"><IndexScan><Object Table="[transactions]"/></IndexScan></RelOp>'
            '<RelOp PhysicalOp="Key Lookup" LogicalOp="Key Lookup" EstimateRows="1" EstimateRebinds="4999" EstimatedTotalSubtreeCost="8.0"><IndexScan><Object Table="[accounts]"/></IndexScan></RelOp>'
            '</NestedLoops></RelOp></QueryPlan></StmtSimple></Statements></Batch></BatchSequence></ShowPlanXML>'
        )
        summary = query_tuner.summarize_showplan_xml(xml)
        flags = " | ".join(summary["flags"])
        self.assertEqual(summary["total_cost"], 12.5)
        self.assertIn("Clustered Index Scan on transactions", flags)
        self.assertIn("Key Lookup on accounts", flags)
        self.assertIn("Nested Loops runs its inner side", flags)
        self.assertIn("missing index", flags)


class TuningApiTests(TunerTestCase):
    def setUp(self) -> None:
        provider = self.client.post("/model-providers", headers=self.headers, json={
            "name": f"Fake tuner {uuid4().hex[:4]}", "provider_type": "openai_compatible", "base_url": "http://model.invalid/v1", "default_model": "fake", "secret_reference": "env:FAKE_MODEL_KEY",
        })
        self.assertEqual(provider.status_code, 201, provider.text)
        routed = self.client.put("/model-routing", headers=self.headers, json={"assignments": {"sql_tuning": provider.json()["id"]}})
        self.assertEqual(routed.status_code, 200, routed.text)

    def tearDown(self) -> None:
        self.client.put("/model-routing", headers=self.headers, json={"assignments": {"sql_tuning": None}})

    def run_job(self, payload: dict, model_replies: list) -> dict:
        with mock.patch.object(query_tuner.LocalExecutor, "timed", fake_timed), mock.patch("app.query_tuner.generate_text", side_effect=model_replies):
            started = self.client.post("/sql/tune", headers=self.headers, json=payload)
            self.assertEqual(started.status_code, 202, started.text)
            for _ in range(200):
                detail = self.client.get(f"/sql/tune/{started.json()['id']}", headers=self.headers).json()
                if detail["status"] in {"SUCCEEDED", "FAILED"}:
                    return detail
                time.sleep(0.05)
        self.fail(f"tuning did not finish: {detail}")

    def test_slow_queries_tune_and_apply_through_approval(self) -> None:
        pid = project_id()
        question = f"Active accounts by type {uuid4().hex[:4]}"
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.email == "admin@datapilot.local"))
            for duration in (900, 1100):
                db.add(QueryRun(project_id=pid, question=question, sql=ORIGINAL, dialect="postgres", result={"execution": {"duration_ms": duration, "row_count": 2}}, status="generated", created_by=admin.id))
            db.commit()
        slow = self.client.get("/sql/slow-queries", headers=self.headers).json()
        entry = next(item for item in slow if item["sql"] == ORIGINAL)
        self.assertEqual((entry["count"], entry["avg_ms"]), (2, 1000.0))
        self.assertEqual(self.client.get("/sql/slow-queries?min_ms=5000", headers=self.headers).json(), [])

        rejected = self.client.post("/sql/tune", headers=self.headers, json={"sql": "DELETE FROM core.accounts"})
        self.assertEqual(rejected.status_code, 422, rejected.text)

        detail = self.run_job({"query_run_id": entry["query_run_id"], "iterations": 3}, replies(WRONG, FAST, FAST_TOO))
        self.assertEqual(detail["status"], "SUCCEEDED", detail)
        report = detail["report"]
        self.assertEqual(report["status"], "improved")
        self.assertEqual(report["winning_sql"], FAST)
        self.assertEqual(report["question"], question)
        self.assertEqual(report["speedup_pct"], 60.0)
        self.assertTrue(any(run["id"] == detail["id"] for run in self.client.get("/sql/tune", headers=self.headers).json()))

        # Nothing changes until an approval is decided.
        with SessionLocal() as db:
            self.assertIsNone(learning.exact_verified(db, pid, question, "postgres", None))
        applied = self.client.post(f"/sql/tune/{detail['id']}/apply", headers=self.headers, json={})
        self.assertTrue(query_tuner.approval_hook_installed())
        self.assertEqual(applied.status_code, 201, applied.text)
        with SessionLocal() as db:
            self.assertIsNone(learning.exact_verified(db, pid, question, "postgres", None))
        self.assertEqual(self.client.post(f"/sql/tune/{detail['id']}/apply", headers=self.headers, json={}).status_code, 409)  # already pending
        decided = self.client.post(f"/approvals/{applied.json()['approval_id']}/decision", headers=self.headers, json={"decision": "approved", "note": "faster"})
        self.assertEqual(decided.status_code, 200, decided.text)
        with SessionLocal() as db:
            verified = learning.exact_verified(db, pid, question, "postgres", None)
            self.assertEqual((verified.sql, verified.source), (FAST, "tuning"))

    def test_run_without_improvement_cannot_be_applied(self) -> None:
        detail = self.run_job({"sql": ORIGINAL, "question": "Active accounts", "iterations": 2}, replies(WRONG, WRONG + " "))
        self.assertEqual(detail["report"]["status"], "no_improvement")
        self.assertEqual(self.client.post(f"/sql/tune/{detail['id']}/apply", headers=self.headers, json={}).status_code, 409)

    def test_rewrite_decision_updates_the_verified_query_only_when_approved(self) -> None:
        pid = project_id()
        question = f"Tuned question {uuid4().hex[:4]}"
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.email == "admin@datapilot.local"))
            learning.upsert_verified(db, pid, question, ORIGINAL, "postgres", None, "manual", admin.id)
            decisions = {}
            for decision in ("rejected", "approved"):
                job = Job(project_id=pid, title="Activate tuned SQL", job_type=query_tuner.APPROVAL_ACTION, status="WAITING_FOR_APPROVAL", progress=10, plan=[], evidence=[], outputs=[], created_by=admin.id)
                db.add(job)
                db.flush()
                approval = Approval(project_id=pid, job_id=job.id, title="Activate tuned SQL", action_type=query_tuner.APPROVAL_ACTION, requested_by=admin.id,
                                    evidence={"tuning_job_id": job.id, "question": question, "sql": FAST, "dialect": "postgres", "connector_id": None})
                db.add(approval)
                db.flush()
                query_tuner.apply_rewrite_decision(db, approval, decision, admin)
                decisions[decision] = (db.scalar(select(VerifiedQuery.sql).where(VerifiedQuery.project_id == pid, VerifiedQuery.question == question)), job.status)
            db.commit()
        self.assertEqual(decisions["rejected"], (ORIGINAL, "CANCELLED"))
        self.assertEqual(decisions["approved"], (FAST, "SUCCEEDED"))

    def test_viewer_role_cannot_start_tuning(self) -> None:
        with mock.patch("app.core.require_any_permission", side_effect=__import__("fastapi").HTTPException(status_code=403, detail="no")):
            response = self.client.post("/sql/tune", headers=self.headers, json={"sql": ORIGINAL})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
