import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-router-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("QDRANT_URL", "")
os.environ.setdefault("SUPERSET_INTERNAL_URL", "")
os.environ.setdefault("SUPERSET_ADMIN_PASSWORD", "")
os.environ.setdefault("SUPERSET_EDITOR_SSO_SECRET", "test-editor-secret")
os.environ.setdefault("ENABLE_DEMO_DATA", "true")

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import decision_router
from app.database import Base, engine
from app.decision_router import DEFAULT_POLICY, assess_risk, follow_up_questions, local_scores
from app.frictionless import metadata_changes, table_schema_type, validate_descriptor
from app.main import app
from app.sql_generation import intent_sql
from app.sqlite_compat import sqlite_compatible_sql
from app.staging import assert_no_application_relations, execute_read_only, referenced_relations


def _tool(name: str, description: str, required: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4().hex, name=name, description=description, purpose="", tags=[], line_of_business="",
        parameter_schema={"type": "object", "required": required or []}, requires_approval=False,
    )


class RiskAssessmentTests(unittest.TestCase):
    def test_word_boundaries_prevent_substring_false_positives(self) -> None:
        for text in ("Describe the writer table", "Rewrite the executive summary", "Summarize customer data"):
            self.assertFalse(assess_risk(text)["requires_approval"], text)

    def test_catches_mutations_the_old_keyword_list_missed(self) -> None:
        self.assertEqual(assess_risk("Update prices by 10%")["level"], "high")
        self.assertTrue(assess_risk("Remove all inactive customers")["requires_approval"])

    def test_negated_mentions_do_not_trigger_but_intervening_words_do(self) -> None:
        # Found with a live Claude plan: "...without altering underlying data" held a read-only run.
        self.assertFalse(assess_risk("Summarize metrics without altering underlying data")["requires_approval"])
        self.assertFalse(assess_risk("Profile data; never modify the source")["requires_approval"])
        self.assertTrue(assess_risk("without hesitation delete all rows")["requires_approval"])
        self.assertEqual(assess_risk("do not delete X but drop table Y")["triggers"], ["drop"])

    def test_inflections_and_multiword_terms(self) -> None:
        self.assertIn("schedule", assess_risk("scheduling a nightly load")["triggers"])
        self.assertIn("create table", assess_risk("please CREATE  TABLE foo")["triggers"])


class LocalScorerTests(unittest.TestCase):
    policy = DEFAULT_POLICY

    def test_grounded_analytic_question_routes_to_sql(self) -> None:
        grounding = {"catalog_matches": [{"relation": "core.accounts", "score": 0.8, "match_type": "vector"}]}
        ranked = local_scores("How many accounts were opened per month?", grounding, [], [], self.policy)
        self.assertEqual(ranked[0]["route"], "sql_analysis")

    def test_matching_published_tool_outranks_ungrounded_sql(self) -> None:
        tool = _tool("account_balance_by_branch", "Account balance totals by branch")
        ranked = local_scores("account balance by branch", {"catalog_matches": []}, [tool], [], self.policy)
        self.assertEqual(ranked[0]["route"], "query_tool")
        self.assertEqual(ranked[0]["target"]["name"], "account_balance_by_branch")

    def test_vague_ungrounded_request_prefers_clarification(self) -> None:
        ranked = local_scores("stuff", {"catalog_matches": []}, [], [], self.policy)
        self.assertEqual(ranked[0]["route"], "clarify")

    def test_multi_step_objective_surfaces_agent_route(self) -> None:
        agent = SimpleNamespace(id="a1", name="Pipeline Builder", purpose="build and deploy pipeline")
        ranked = local_scores("Build a pipeline and then schedule it", {"catalog_matches": []}, [], [agent], self.policy)
        self.assertEqual(ranked[0]["route"], "agent_run")
        self.assertEqual(ranked[0]["target"]["name"], "Pipeline Builder")

    def test_jev_failure_falls_back_to_local(self) -> None:
        with mock.patch.dict(os.environ, {"DECISION_ROUTER_BACKEND": "jev", "TYPESAFE_API_URL": "", "TYPESAFE_API_KEY": ""}):
            db = mock.MagicMock()
            db.scalars.return_value.all.return_value = []
            decision = decision_router.decide(db, "p1", "How many accounts?", {"catalog_matches": []})
        self.assertEqual(decision["backend"], "local (jev unavailable)")
        self.assertIn(decision["route"], decision_router.ROUTES)

    def test_jev_distribution_reorders_candidates(self) -> None:
        with mock.patch.dict(os.environ, {"DECISION_ROUTER_BACKEND": "jev"}), \
                mock.patch.object(decision_router, "_jev_choice", return_value={"clarify": 0.9, "sql_analysis": 0.1}):
            db = mock.MagicMock()
            db.scalars.return_value.all.return_value = []
            decision = decision_router.decide(db, "p1", "How many accounts?", {"catalog_matches": []})
        self.assertEqual(decision["route"], "clarify")
        self.assertTrue(decision["backend"].startswith("jev"))
        # Risk stays deterministic regardless of the decision model.
        self.assertEqual(decision["risk"], assess_risk("How many accounts?"))

    def test_follow_ups_use_result_columns(self) -> None:
        ideas = follow_up_questions("accounts", {"columns": ["open_month", "branch", "total"], "rows": [{"open_month": "2026-01", "branch": "A", "total": 3}], "row_count": 1})
        self.assertTrue(any("trend of total by open_month" in idea for idea in ideas))


class SqlGuardTests(unittest.TestCase):
    def test_blocks_application_and_system_tables(self) -> None:
        for sql in (
            "SELECT email, password_hash FROM users",
            'select * from "users"',
            "select x from (select * from users) t",
            "select * from staging.a, public.model_providers p",
            "with t as (select * from audit_events) select * from t",
            "select * from pg_catalog.pg_authid",
        ):
            with self.assertRaises(ValueError, msg=sql):
                assert_no_application_relations(sql)

    def test_allows_staged_relations_and_literals(self) -> None:
        for sql in (
            "select * from staging.users u join core.accounts a on a.id = u.id",
            "select users from staging.t",
            "select 1 from core.accounts where name = 'from users'",
        ):
            assert_no_application_relations(sql)
        self.assertEqual(referenced_relations("select * from core.accounts a join staging.b on 1=1"), [("core", "accounts"), ("staging", "b")])


class LocalSqlTests(unittest.TestCase):
    accounts = SimpleNamespace(schema_name="core", table_name="accounts", asset_type="table", columns=[
        {"name": "account_id", "type": "INTEGER"}, {"name": "account_type", "type": "VARCHAR(30)"},
        {"name": "status", "type": "VARCHAR(30)"}, {"name": "opened_at", "type": "DATETIME"}, {"name": "balance", "type": "NUMERIC(12,2)"},
    ])

    def test_intent_sql_follows_the_question(self) -> None:
        self.assertIn('GROUP BY "account_type"', intent_sql("How many accounts by account type?", "postgres", [self.accounts]))
        self.assertIn("DATE_TRUNC('month', \"opened_at\")", intent_sql("Show monthly account growth", "postgres", [self.accounts]))
        self.assertIn("\"status\" = 'active'", intent_sql("How many active accounts?", "postgres", [self.accounts]))
        self.assertIn('AVG("balance")', intent_sql("average balance by status", "postgres", [self.accounts]))
        top = intent_sql("top 2 account type by count", "sqlserver", [self.accounts])
        self.assertTrue(top.startswith("SELECT TOP (2)") and "[account_type]" in top, top)
        self.assertIsNone(intent_sql("stuff", "postgres", [self.accounts]))

    def test_sqlite_rewrites_common_postgres_syntax(self) -> None:
        rewritten = sqlite_compatible_sql(
            "SELECT DATE_TRUNC('month', a.opened_at) FROM core.accounts AS a WHERE a.opened_at >= CURRENT_TIMESTAMP - INTERVAL '12 months' AND a.opened_at::date > '2020-01-01' AND a.status ILIKE 'act%'",
            {"accounts"},
        )
        self.assertIn("datetime('now', '-12 months')", rewritten)
        self.assertIn('FROM "accounts" AS a', rewritten)
        self.assertIn("CAST(a.opened_at AS TEXT)", rewritten)
        self.assertIn(" LIKE ", rewritten)
        self.assertIn("a.opened_at", rewritten)  # aliases are untouched

    def test_failed_or_fallback_sql_is_never_cached(self) -> None:
        from app.main import _cacheable_sql_result

        self.assertTrue(_cacheable_sql_result({"execution": {"rows": []}, "provider": {"mode": "deterministic_local"}}))
        self.assertFalse(_cacheable_sql_result({"execution": {"error": "syntax error"}, "provider": {"mode": "deterministic_local"}}))
        self.assertFalse(_cacheable_sql_result({"execution": None, "provider": {"mode": "deterministic_safety_fallback"}}))

    def test_schema_stripping_cannot_reach_app_tables(self) -> None:
        Base.metadata.create_all(engine)  # this class can run before the app's startup creates tables
        with self.assertRaises(ValueError):
            execute_read_only(engine, "select * from core.users", 5)


class FrictionlessTests(unittest.TestCase):
    def test_type_mapping(self) -> None:
        self.assertEqual(table_schema_type("BIGINT"), "integer")
        self.assertEqual(table_schema_type("timestamp with time zone"), "datetime")
        self.assertEqual(table_schema_type("NUMERIC(10,2)"), "number")
        self.assertEqual(table_schema_type("varchar"), "string")

    def test_descriptor_validation(self) -> None:
        self.assertTrue(validate_descriptor({"resources": []}))
        self.assertIn("resources[0].name must match ^[a-z0-9._-]+$", validate_descriptor({"resources": [{"name": "Bad Name", "path": "x"}]}))
        self.assertEqual(validate_descriptor({"resources": [{"name": "ok", "path": "x", "schema": {"fields": [{"name": "a"}]}}]}), [])

    def test_import_only_touches_descriptive_metadata(self) -> None:
        asset = SimpleNamespace(columns=[{"name": "id", "type": "integer"}])
        patch = metadata_changes(asset, {
            "description": "Accounts",
            "schema": {"fields": [{"name": "id", "title": "Account ID", "type": "string"}, {"name": "ghost", "title": "x"}]},
        })
        self.assertEqual(patch, {"description": "Accounts", "column_notes": {"id": {"business_name": "Account ID"}}})


class RouterApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        token = cls.client.post("/auth/login", json={"email": "admin@datapilot.local", "password": "ChangeMe123!"}).json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        if database_file.exists():
            database_file.unlink()

    def test_conversation_answer_carries_route_and_follow_ups(self) -> None:
        conversation = self.client.post("/conversations", headers=self.headers, json={"title": "Router"}).json()
        answer = self.client.post(
            f"/conversations/{conversation['id']}/messages",
            headers=self.headers,
            json={"content": "Show monthly account growth", "dialect": "postgres"},
        )
        self.assertEqual(answer.status_code, 201, answer.text)
        structured = answer.json()["structured"]
        self.assertIn(structured["route"]["route"], decision_router.ROUTES)
        self.assertEqual(structured["route"]["policy_version"], "local-v1")
        self.assertIsInstance(structured["follow_ups"], list)
        listed = self.client.get("/conversations", headers=self.headers).json()
        mine = next(item for item in listed if item["id"] == conversation["id"])
        self.assertEqual(mine["message_count"], 2)
        self.assertTrue(mine["last_message"])
        decisions = self.client.get("/router/decisions", headers=self.headers).json()
        self.assertTrue(any(row["message_id"] == answer.json()["id"] for row in decisions))

    def test_preview_and_policy_endpoints(self) -> None:
        preview = self.client.post("/router/decide", headers=self.headers, json={"question": "delete stale accounts"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["risk"]["level"], "high")
        self.assertEqual(self.client.get("/router/policy", headers=self.headers).json()["version"], "local-v1")

    def test_sql_execute_rejects_metadata_tables(self) -> None:
        response = self.client.post("/sql/execute", headers=self.headers, json={"sql": "SELECT email, password_hash FROM users", "dialect": "postgres"})
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn("pbkdf2", response.text)

    def test_viewer_cannot_run_sql_agents_or_tools(self) -> None:
        email = f"viewer-{uuid4().hex[:8]}@datapilot.local"
        created = self.client.post("/admin/users", headers=self.headers, json={"email": email, "name": "Viewer", "role": "viewer", "temporary_password": "TempPass1234!"})
        self.assertEqual(created.status_code, 201, created.text)
        token = self.client.post("/auth/login", json={"email": email, "password": "TempPass1234!"}).json()["access_token"]
        viewer = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.post("/sql/execute", headers=viewer, json={"sql": "select 1", "dialect": "postgres"}).status_code, 403)
        self.assertEqual(self.client.post("/sql/generate", headers=viewer, json={"question": "count accounts", "dialect": "postgres"}).status_code, 403)
        self.assertEqual(self.client.post("/agents/runs", headers=viewer, json={"objective": "Summarize data"}).status_code, 403)

    def test_failed_generation_leaves_no_orphan_user_message(self) -> None:
        conversation = self.client.post("/conversations", headers=self.headers, json={"title": "Failure"}).json()
        with mock.patch("app.routers.conversations.generate_sql", side_effect=HTTPException(status_code=422, detail="Model generation failed: boom")):
            failed = self.client.post(f"/conversations/{conversation['id']}/messages", headers=self.headers, json={"content": "How many accounts?", "dialect": "postgres"})
        self.assertEqual(failed.status_code, 422)
        messages = self.client.get(f"/conversations/{conversation['id']}/messages", headers=self.headers).json()
        self.assertEqual(messages, [])

    def test_local_answer_executes_question_specific_sql(self) -> None:
        conversation = self.client.post("/conversations", headers=self.headers, json={"title": "Local"}).json()
        answer = self.client.post(
            f"/conversations/{conversation['id']}/messages",
            headers=self.headers,
            json={"content": "How many accounts by account type?", "dialect": "postgres"},
        ).json()["structured"]
        self.assertIn("account_type", answer["sql"])
        self.assertIsNone(answer["execution"].get("error"), answer["execution"].get("error"))
        self.assertGreater(answer["execution"]["row_count"], 0)

    def test_datapackage_round_trip(self) -> None:
        datasets = self.client.get("/datasets", headers=self.headers).json()
        self.assertTrue(datasets)
        asset = datasets[0]
        package = self.client.get(f"/datasets/{asset['id']}/datapackage", headers=self.headers)
        self.assertEqual(package.status_code, 200, package.text)
        descriptor = package.json()
        self.assertEqual(self.client.post("/datapackage/validate", headers=self.headers, json=descriptor).json(), {"valid": True, "errors": []})
        field = descriptor["resources"][0]["schema"]["fields"][0]
        field["title"] = "Curated title"
        applied = self.client.post(f"/datasets/{asset['id']}/datapackage", headers=self.headers, json=descriptor)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertIn(field["name"], applied.json()["columns_updated"])
        project_package = self.client.get("/datapackage", headers=self.headers).json()
        self.assertGreaterEqual(len(project_package["resources"]), 1)


if __name__ == "__main__":
    unittest.main()
