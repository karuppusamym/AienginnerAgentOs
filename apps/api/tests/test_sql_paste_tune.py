"""Paste & run, plan analysis and long-query tuning (POST /sql/run, POST /sql/analyze, piece-wise CTE rewrites)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-paste-{uuid4().hex}.db"
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

from app import query_tuner
from app.database import SessionLocal, engine
from app.main import app
from app.model_runtime import ProviderGenerationResult
from app.models import ModelProvider, Project

SLOW_BODY = "\n    SELECT a.account_id, a.account_type FROM core.accounts a\n    WHERE a.account_id IN (SELECT b.account_id FROM core.accounts b WHERE b.status = 'active')\n  "
FAST_BODY = "SELECT account_id, account_type FROM core.accounts WHERE status = 'active'"
WRONG_BODY = "SELECT a.account_id, a.account_type FROM core.accounts a"  # keeps inactive accounts
PADDING = ",\n".join(f"      COUNT(*) AS c{index}" for index in range(330))
LONG_WITH = (
    "-- Long pasted report: active accounts by type\n"
    f"WITH active AS ({SLOW_BODY}),\n"
    "  padding AS (\n    SELECT account_type,\n" + PADDING + "\n    FROM core.accounts\n    GROUP BY account_type\n  )\n"
    "SELECT act.account_type, COUNT(*) AS n\nFROM active act\nGROUP BY act.account_type\nORDER BY act.account_type"
)
# EXPLAIN ANALYZE of a query whose cost sits in the materialised CTE "active".
CTE_PLAN = [{"Plan": {"Node Type": "Aggregate", "Total Cost": 120.0, "Plan Rows": 2, "Actual Rows": 2, "Actual Loops": 1, "Actual Total Time": 100.0,
                      "Plans": [{"Node Type": "CTE Scan", "CTE Name": "active", "Parent Relationship": "Outer", "Total Cost": 110.0, "Plan Rows": 5, "Actual Rows": 5, "Actual Loops": 1, "Actual Total Time": 95.0}]},
             "Execution Time": 100.5}]
# A plan with every issue the analysis must explain in plain language.
BAD_PLAN = [{"Plan": {
    "Node Type": "Sort", "Total Cost": 90_000.0, "Plan Rows": 100, "Actual Rows": 100, "Actual Loops": 1, "Actual Total Time": 900.0,
    "Sort Space Type": "Disk", "Sort Space Used": 40_960, "Sort Method": "external merge",
    "Plans": [{
        "Node Type": "Nested Loop", "Parent Relationship": "Outer", "Total Cost": 80_000.0, "Plan Rows": 100, "Actual Rows": 400_000, "Actual Loops": 1, "Actual Total Time": 800.0,
        "Plans": [
            {"Node Type": "Seq Scan", "Relation Name": "transactions", "Parent Relationship": "Outer", "Total Cost": 5_000.0, "Plan Rows": 1_000, "Actual Rows": 20_000, "Actual Loops": 1,
             "Actual Total Time": 300.0, "Rows Removed by Filter": 180_000, "Filter": "(amount > 10)"},
            {"Node Type": "Materialize", "Parent Relationship": "Inner", "Total Cost": 50.0, "Plan Rows": 20, "Actual Rows": 20, "Actual Loops": 20_000, "Actual Total Time": 0.01,
             "Plans": [{"Node Type": "Seq Scan", "Relation Name": "branches", "Parent Relationship": "Outer", "Total Cost": 40.0, "Plan Rows": 20, "Actual Rows": 20, "Actual Loops": 1, "Actual Total Time": 0.05}]},
            {"Node Type": "Index Scan", "Relation Name": "accounts", "Parent Relationship": "SubPlan", "Subplan Name": "SubPlan 1", "Total Cost": 1.0, "Plan Rows": 1, "Actual Rows": 1, "Actual Loops": 20_000, "Actual Total Time": 0.004},
        ],
    }],
}, "Execution Time": 910.0, "Planning Time": 1.2}]


def replies(*bodies):
    return [ProviderGenerationResult(content=__import__("json").dumps({"sql": body, "notes": f"rewrite {index}"}), latency_ms=1) for index, body in enumerate(bodies)]


def fake_timed(self, sql, limit):
    """Real execution (equivalence is real); simulated clock: the IN-subquery version is slow."""
    return self.run(sql, limit), (100.0 if "IN (SELECT" in sql else 40.0)


def fake_provider() -> ModelProvider:
    return ModelProvider(name="Fake tuner", provider_type="openai_compatible", default_model="fake", enabled=True)


def project_id() -> str:
    with SessionLocal() as db:
        return db.scalar(select(Project.id).where(Project.slug == "retail-banking"))


class PasteTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        token = cls.client.post("/auth/login", json={"email": "admin@datapilot.local", "password": "ChangeMe123!"}).json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)


class PasteAndRunTests(PasteTestCase):
    def test_thousand_line_pasted_query_runs_with_comments_and_timing(self) -> None:
        measures = "\n".join(f"  SUM(CASE WHEN status = 'active' THEN {index} ELSE 0 END) AS m{index}," for index in range(1_100))
        sql = f"-- Pasted monthly report; update later\nSELECT account_type,\n{measures}\n  COUNT(*) AS n\nFROM core.accounts\n/* delete; drop: just a comment */\nGROUP BY account_type\nORDER BY account_type;"
        self.assertGreater(sql.count("\n"), 1_000)
        response = self.client.post("/sql/run", headers=self.headers, json={"sql": sql, "limit": 50, "timeout_seconds": 60})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ok", body.get("error"))
        self.assertGreater(body["lines"], 1_000)
        self.assertGreaterEqual(body["row_count"], 1)
        self.assertEqual(len(body["columns"]), 1_102)
        self.assertIsInstance(body["duration_ms"], float)
        self.assertIn("slow_threshold_ms", body)
        self.assertEqual(body["limit"], 50)

    def test_errors_point_at_the_failing_line(self) -> None:
        sql = "SELECT account_id,\n       account_type\nFROM core.accounts\nWHERE status = = 'active'"
        body = self.client.post("/sql/run", headers=self.headers, json={"sql": sql}).json()
        self.assertEqual((body["status"], body["stage"]), ("error", "guard"))
        self.assertEqual(body["error"]["line"], 4)
        self.assertIn("status", body["error"]["snippet"])
        write = self.client.post("/sql/run", headers=self.headers, json={"sql": "DELETE FROM core.accounts"}).json()
        self.assertEqual((write["status"], write["stage"]), ("error", "guard"))
        outside = self.client.post("/sql/run", headers=self.headers, json={"sql": "SELECT * FROM secret_schema.payroll"}).json()
        self.assertEqual(outside["stage"], "catalog")
        failing = self.client.post("/sql/run", headers=self.headers, json={"sql": "SELECT account_id,\n  no_such_column\nFROM core.accounts"}).json()
        self.assertEqual((failing["status"], failing["stage"]), ("error", "execution"))
        self.assertIn("no_such_column", failing["error"]["message"])

    def test_locate_sql_error_uses_driver_position_and_near_token(self) -> None:
        class Diag:
            statement_position = "27"

        class DriverError(Exception):
            diag = Diag()

        sql = "SELECT a\nFROM t\nWHERE x = y"
        located = query_tuner.locate_sql_error(sql, DriverError("column y does not exist"))
        self.assertEqual((located["line"], located["column"]), (3, 11))
        near = query_tuner.locate_sql_error("SELECT a\nFORM t", Exception('near "FORM": syntax error'))
        self.assertEqual((near["line"], near["column"]), (2, 1))

    def test_comment_masking_and_cte_split_keep_offsets(self) -> None:
        sql = "WITH a AS (SELECT 1 AS x -- ) not a paren\n), \"b c\" AS MATERIALIZED (SELECT ')' AS y FROM a)\nSELECT * FROM a, \"b c\""
        masked = query_tuner.mask_sql_comments(sql)
        self.assertEqual(len(masked), len(sql))
        self.assertNotIn("not a paren", masked)
        split = query_tuner.split_ctes(sql)
        self.assertEqual([cte["name"] for cte in split["ctes"]], ["a", "b c"])
        self.assertEqual(sql[split["ctes"][1]["start"]:split["ctes"][1]["end"]], "SELECT ')' AS y FROM a")
        rebuilt = query_tuner.replace_cte_bodies(sql, split, {"b c": "SELECT 2 AS y"})
        self.assertIn("MATERIALIZED (\nSELECT 2 AS y\n)", rebuilt)
        self.assertTrue(rebuilt.startswith("WITH a AS (SELECT 1 AS x -- ) not a paren\n)"))
        self.assertIsNone(query_tuner.split_ctes("SELECT 1"))


class PlanAnalysisTests(PasteTestCase):
    def test_postgres_plan_issues_in_plain_language(self) -> None:
        summary = query_tuner.summarize_postgres_plan(BAD_PLAN)
        kinds = {item["kind"] for item in summary["issues"]}
        self.assertTrue({"seq_scan", "sort_spill", "nested_loop", "repeated_subquery", "missing_join_filter"} <= kinds, kinds)
        seq = next(item for item in summary["issues"] if item["kind"] == "seq_scan")
        self.assertEqual(seq["relation"], "transactions")
        self.assertIn("200,000", seq["detail"])
        self.assertTrue(all(0 <= (node.get("share_pct") or 0) <= 100 for node in summary["nodes"]))
        self.assertEqual(summary["nodes"][0]["node"], "Seq Scan")  # most exclusive time first

    def test_static_issues_non_sargable_repeated_subquery_and_cartesian_join(self) -> None:
        sql = (
            "SELECT t.account_id FROM core.transactions t, core.branches b "
            "WHERE CAST(t.posted_at AS DATE) = '2024-01-01' AND LOWER(t.channel) = 'web' AND t.description LIKE '%fee%' "
            "AND t.amount > (SELECT AVG(x.amount) FROM core.transactions x WHERE x.channel = 'web') "
            "AND t.amount < (SELECT AVG(x.amount) FROM core.transactions x WHERE x.channel = 'web') * 10"
        )
        issues = query_tuner.static_sql_issues(sql, "postgres")
        titles = [item["title"] for item in issues]
        self.assertEqual(sum(1 for item in issues if item["title"] == "Non-sargable predicate"), 2, titles)
        self.assertIn("Leading-wildcard LIKE", titles)
        self.assertTrue(any(item["kind"] == "repeated_subquery" for item in issues), titles)
        self.assertTrue(any(item["kind"] == "missing_join_filter" for item in issues), titles)
        joined = query_tuner.static_sql_issues("SELECT 1 FROM core.transactions t, core.accounts a WHERE t.account_id = a.account_id", "postgres")
        self.assertFalse(any(item["kind"] == "missing_join_filter" for item in joined))

    def test_analyze_endpoint_returns_operators_issues_and_index_suggestions(self) -> None:
        summary = query_tuner.summarize_postgres_plan([{"Plan": {"Node Type": "Seq Scan", "Relation Name": "accounts", "Total Cost": 500.0, "Plan Rows": 10, "Actual Rows": 60_000,
                                                                 "Actual Loops": 1, "Actual Total Time": 700.0, "Rows Removed by Filter": 40_000}, "Execution Time": 701.0}])
        sql = "SELECT account_type, COUNT(*) AS n FROM core.accounts WHERE status = 'active' GROUP BY account_type"
        with mock.patch.object(query_tuner.LocalExecutor, "explain", lambda self, sql, analyze: summary):
            response = self.client.post("/sql/analyze", headers=self.headers, json={"sql": sql, "duration_ms": 1_200})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["slow"] and body["recommend_rewrite"])
        self.assertEqual(body["operators"][0]["relation"], "accounts")
        self.assertEqual(body["operators"][0]["share_pct"], 100.0)
        self.assertEqual(body["issues"][0]["kind"], "seq_scan")
        suggestion = next(item for item in body["index_suggestions"] if item["columns"] == ["status"])
        self.assertEqual(suggestion["relation"], "core.accounts")
        self.assertTrue(suggestion["full_scan"])
        self.assertIn("CREATE INDEX", suggestion["statement"])
        rejected = self.client.post("/sql/analyze", headers=self.headers, json={"sql": "DELETE FROM core.accounts"})
        self.assertEqual(rejected.status_code, 422)


class LongQueryTuningTests(PasteTestCase):
    def tune(self, sql: str, model_replies: list, iterations: int = 4, plan=None, on_report=None):
        explain = (lambda self, sql, analyze: query_tuner.summarize_postgres_plan(plan)) if plan else query_tuner.LocalExecutor.explain
        with SessionLocal() as db, mock.patch.object(query_tuner.LocalExecutor, "timed", fake_timed), mock.patch.object(query_tuner.LocalExecutor, "explain", explain), \
                mock.patch("app.query_tuner.generate_text", side_effect=model_replies) as generate:
            report = query_tuner.tune_query(db, engine, sql, "postgres", "Active accounts by type", iterations, fake_provider(), project_id=project_id(), on_report=on_report)
        return report, generate

    def test_token_budget_scales_with_length_and_timeout_is_passed(self) -> None:
        self.assertEqual(query_tuner.rewrite_token_budget("SELECT 1"), query_tuner.MIN_REWRITE_TOKENS)
        self.assertEqual(query_tuner.rewrite_token_budget("x" * 30_000), 30_000 // 3 + 800)
        self.assertEqual(query_tuner.rewrite_token_budget("x" * 400_000), query_tuner.MAX_REWRITE_TOKENS)
        notes = "".join(f"-- context line {index}: this report was pasted from the finance team's long query\n" for index in range(60))
        original = notes + "SELECT a.account_type, COUNT(*) AS n FROM core.accounts a WHERE a.account_id IN (SELECT b.account_id FROM core.accounts b WHERE b.status = 'active') GROUP BY a.account_type"
        fast = "SELECT account_type, COUNT(*) AS n FROM core.accounts WHERE status = 'active' GROUP BY account_type"
        report, generate = self.tune(original, replies(fast), iterations=1)
        self.assertEqual(report["mode"], "whole")
        self.assertEqual(report["status"], "improved")
        call = generate.call_args_list[0]
        self.assertEqual(call.args[3], query_tuner.rewrite_token_budget(original.strip()))
        self.assertGreater(call.args[3], query_tuner.MIN_REWRITE_TOKENS)
        self.assertEqual(call.kwargs["timeout"], 120)

    def test_piecewise_rewrite_of_costly_cte_is_accepted_only_when_whole_query_is_equivalent(self) -> None:
        self.assertGreater(LONG_WITH.count("\n"), 300)
        snapshots = []
        broken = "SELECT 1 AS account_id) , sneaky AS (SELECT 2"
        report, generate = self.tune(LONG_WITH, replies(WRONG_BODY, FAST_BODY, broken, FAST_BODY), iterations=4, plan=CTE_PLAN, on_report=lambda partial: snapshots.append(len(partial["attempts"])))
        self.assertEqual(report["mode"], "piecewise")
        self.assertEqual(report["cte_targets"], ["active"])
        first, second, third = report["attempts"][:3]
        self.assertEqual(first["part"], "active")
        self.assertFalse(first["equivalent"])
        self.assertIn("not equivalent", first["rejected_reason"])
        self.assertTrue(second["equivalent"] and second["improved"])
        self.assertIn("structure", third["rejected_reason"])  # a body that closes the CTE early is refused
        self.assertEqual(report["status"], "improved")
        winner = report["winning_sql"]
        self.assertIn(FAST_BODY, winner)
        self.assertNotIn("IN (SELECT", winner)
        # Everything outside the rewritten CTE is byte-for-byte the original.
        self.assertIn("padding AS (\n    SELECT account_type,\n" + PADDING + "\n    FROM core.accounts", winner)
        self.assertTrue(winner.endswith("ORDER BY act.account_type"))
        self.assertTrue(any(line.startswith("+") and FAST_BODY in line for line in report["diff"]))
        # The model only sees the costly CTE in full, with a longer timeout and a budget sized to that CTE.
        call = generate.call_args_list[0]
        self.assertEqual(call.args[1], query_tuner.PIECE_SYSTEM)
        self.assertIn("Rewrite the body of CTE `active`", call.args[2])
        self.assertNotIn("c250", call.args[2])
        self.assertEqual(call.args[3], query_tuner.rewrite_token_budget(SLOW_BODY.strip()))
        self.assertEqual(call.kwargs["timeout"], 120)
        self.assertEqual(snapshots, [0, 1, 2, 3, 4])  # live progress after the baseline and each attempt

    def test_piecewise_non_equivalent_rewrites_are_never_accepted(self) -> None:
        report, _ = self.tune(LONG_WITH, replies(WRONG_BODY, WRONG_BODY + " WHERE 1 = 1"), iterations=2, plan=CTE_PLAN)
        self.assertEqual(report["status"], "no_improvement")
        self.assertIsNone(report["winning_sql"])
        self.assertTrue(all(not attempt["equivalent"] for attempt in report["attempts"]))

    def test_cte_ranking_without_a_plan_uses_structure(self) -> None:
        ranked = query_tuner.rank_ctes(LONG_WITH, "postgres", None)
        self.assertEqual({item["name"] for item in ranked}, {"active", "padding"})
        self.assertEqual(ranked[0]["basis"], "structure")
        with_plan = query_tuner.rank_ctes(LONG_WITH, "postgres", query_tuner.summarize_postgres_plan(CTE_PLAN))
        self.assertEqual((with_plan[0]["name"], with_plan[0]["share_pct"]), ("active", 100.0))


if __name__ == "__main__":
    unittest.main()
