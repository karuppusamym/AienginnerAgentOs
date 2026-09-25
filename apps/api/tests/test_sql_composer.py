import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-composer-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("QDRANT_URL", "")
os.environ.setdefault("SUPERSET_INTERNAL_URL", "")
os.environ.setdefault("SUPERSET_ADMIN_PASSWORD", "")
os.environ.setdefault("SUPERSET_EDITOR_SSO_SECRET", "test-editor-secret")
os.environ.setdefault("ENABLE_DEMO_DATA", "true")
os.environ["DECISION_ROUTER_BACKEND"] = "local"

from fastapi.testclient import TestClient

from app import sql_composer
from app.database import engine
from app.main import app
from app.model_runtime import ProviderGenerationResult
from app.sql_guard import check_read_only
from app.staging import execute_read_only

CATALOG = {
    "core.accounts": {
        "columns": [
            {"name": "account_id", "type": "integer"},
            {"name": "customer_id", "type": "integer"},
            {"name": "account_type", "type": "varchar"},
            {"name": "status", "type": "varchar"},
            {"name": "opened_at", "type": "timestamp"},
        ],
        "description": "Demo accounts",
    }
}

TWO_STEP_PLAN = {
    "title": "Active accounts by type",
    "steps": [
        {"name": "active_accounts", "purpose": "Keep active accounts", "inputs": ["core.accounts"], "columns": [{"name": "account_id"}, {"name": "account_type"}], "rules": ["status = 'active'"]},
        {"name": "type_counts", "purpose": "Count per type", "depends_on": ["active_accounts"], "inputs": ["active_accounts"], "columns": [{"name": "account_type"}, {"name": "n"}], "rules": ["one row per account_type"]},
    ],
    "final": {"purpose": "Return counts", "depends_on": ["type_counts"], "columns": [{"name": "account_type"}, {"name": "n"}]},
}

STEP_SQL = {
    "active_accounts": "SELECT account_id, account_type FROM core.accounts WHERE status = 'active'",
    "type_counts": "SELECT account_type, COUNT(*) AS n FROM active_accounts GROUP BY account_type",
    "final": "SELECT account_type, n FROM type_counts",
}


def step_name(prompt: str) -> str:
    return re.search(r"^Step: (\w+)$", prompt, re.M).group(1)


def execute_local(sql: str) -> dict:
    try:
        return execute_read_only(engine, sql, sql_composer.PREVIEW_ROWS)
    except Exception as exc:
        return {"error": str(exc), "columns": [], "rows": [], "row_count": 0}


class ComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Starting the app creates the database and the demo core.accounts table the builds execute against.
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

    # ------------------------------------------------------------------ plan validation

    def test_valid_plan_is_normalized_into_dependency_order(self) -> None:
        shuffled = {**TWO_STEP_PLAN, "steps": list(reversed(TWO_STEP_PLAN["steps"]))}
        plan, errors = sql_composer.normalize_plan(shuffled, CATALOG)
        self.assertEqual(errors, [])
        self.assertEqual([step["name"] for step in plan["steps"]], ["active_accounts", "type_counts"])
        self.assertEqual(plan["final"]["depends_on"], ["type_counts"])
        # Bare catalogue names resolve to schema.table.
        bare, errors = sql_composer.normalize_plan({"steps": [{"name": "a", "inputs": ["accounts"]}]}, CATALOG)
        self.assertEqual((errors, bare["steps"][0]["inputs"], bare["final"]["depends_on"]), ([], ["core.accounts"], ["a"]))

    def test_cycles_are_rejected(self) -> None:
        _, errors = sql_composer.normalize_plan({"steps": [
            {"name": "a", "inputs": ["core.accounts", "c"]},
            {"name": "b", "inputs": ["a"]},
            {"name": "c", "inputs": ["b"]},
        ]}, CATALOG)
        self.assertTrue(any("cycle" in error.lower() and "a, b, c" in error for error in errors), errors)
        _, self_errors = sql_composer.normalize_plan({"steps": [{"name": "a", "inputs": ["core.accounts"], "depends_on": ["a"]}]}, CATALOG)
        self.assertTrue(any("cycle" in error for error in self_errors), self_errors)

    def test_unknown_relations_bad_names_and_duplicates_are_rejected(self) -> None:
        _, errors = sql_composer.normalize_plan({"steps": [
            {"name": "leak", "inputs": ["public.users"]},
            {"name": "Bad-Name", "inputs": ["core.accounts"]},
            {"name": "select", "inputs": ["core.accounts"]},
            {"name": "accounts", "inputs": ["core.accounts"]},
            {"name": "dup", "inputs": ["core.accounts"]},
            {"name": "dup", "inputs": ["core.accounts"], "depends_on": ["ghost"]},
        ]}, CATALOG)
        joined = "\n".join(errors)
        self.assertIn("'public.users' is neither a catalogued relation", joined)
        self.assertIn("not a valid identifier", joined)
        self.assertIn("reserved SQL word", joined)
        self.assertIn("shadows a catalog table", joined)
        self.assertIn("Duplicate step name 'dup'", joined)
        self.assertIn("unknown step 'ghost'", joined)
        with self.assertRaises(sql_composer.PlanError):
            sql_composer.extract_json("no json here")
        self.assertEqual(sql_composer.extract_json('```json\n{"steps": []}\n```'), {"steps": []})

    # ------------------------------------------------------------------ build

    def test_steps_build_separately_and_assemble_into_one_guarded_with_statement(self) -> None:
        plan, _ = sql_composer.normalize_plan(TWO_STEP_PLAN, CATALOG)
        prompts: list[str] = []

        def generate(system: str, prompt: str, max_tokens: int) -> str:
            prompts.append(prompt)
            return f"```sql\n{STEP_SQL[step_name(prompt)]};\n```"

        result = sql_composer.build_program(plan, sql_composer.ComposeContext(dialect="postgres", catalog=CATALOG, generate=generate, execute=execute_local))
        self.assertEqual(result["status"], "completed", result["validation"])
        self.assertTrue(result["sql"].startswith("WITH\n"))
        self.assertEqual(result["sql"].count(" AS (\n"), 2)
        self.assertTrue(check_read_only(result["sql"], "postgres").ok)
        self.assertEqual([step["status"] for step in result["steps"]], ["ok", "ok"])
        self.assertGreater(result["steps"][0]["row_count"], 0)
        self.assertEqual(result["steps"][1]["columns"], ["account_type", "n"])
        self.assertEqual(sorted(row["account_type"] for row in result["preview"]), ["checking", "savings"])
        self.assertEqual(result["lineage"], {"active_accounts": ["core.accounts"], "type_counts": ["active_accounts"], "final": ["type_counts"]})
        # Each prompt carries only that step's inputs: the first never sees later steps, the second never sees the raw table.
        first = next(prompt for prompt in prompts if step_name(prompt) == "active_accounts")
        second = next(prompt for prompt in prompts if step_name(prompt) == "type_counts")
        self.assertIn("core.accounts", first)
        self.assertNotIn("type_counts", first.split("<catalog>")[1])
        self.assertNotIn("core.accounts", second.split("<catalog>")[1])
        self.assertIn("account_type", second.split("<catalog>")[1])  # executed columns of the upstream step

    def test_failing_step_gets_one_targeted_repair_with_the_database_error(self) -> None:
        plan, _ = sql_composer.normalize_plan(TWO_STEP_PLAN, CATALOG)
        repair_prompts: list[str] = []

        def generate(system: str, prompt: str, max_tokens: int) -> str:
            name = step_name(prompt)
            if name == "type_counts" and system == sql_composer.STEP_SYSTEM:
                return "SELECT account_kind, COUNT(*) AS n FROM active_accounts GROUP BY account_kind"
            if system == sql_composer.REPAIR_SYSTEM:
                repair_prompts.append(prompt)
            return STEP_SQL[name]

        ctx = sql_composer.ComposeContext(dialect="postgres", catalog=CATALOG, generate=generate, execute=execute_local)
        result = sql_composer.build_program(plan, ctx)
        self.assertEqual(result["status"], "completed", result["validation"])
        repaired = result["steps"][1]
        self.assertEqual((repaired["status"], repaired["attempts"]), ("repaired", 2))
        self.assertIn("Database error", repaired["repaired_from"])
        self.assertEqual(len(repair_prompts), 1)
        self.assertIn("account_kind", repair_prompts[0])  # the candidate and its error are sent back
        self.assertEqual(result["stats"]["repairs"], 1)

    def test_dml_in_a_step_is_rejected_and_dependents_are_skipped(self) -> None:
        plan, _ = sql_composer.normalize_plan(TWO_STEP_PLAN, CATALOG)

        def generate(system: str, prompt: str, max_tokens: int) -> str:
            if step_name(prompt) == "active_accounts":
                return "DELETE FROM core.accounts" if system == sql_composer.STEP_SYSTEM else "UPDATE core.accounts SET status = 'x'"
            return STEP_SQL[step_name(prompt)]

        executed: list[str] = []
        result = sql_composer.build_program(plan, sql_composer.ComposeContext(dialect="postgres", catalog=CATALOG, generate=generate, execute=lambda sql: executed.append(sql) or {"rows": [], "columns": []}))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["sql"], "")
        self.assertEqual([step["status"] for step in result["steps"]], ["failed", "skipped"])
        self.assertIn("SELECT", result["steps"][0]["error"])
        self.assertEqual(executed, [])  # nothing unsafe ever reaches the executor
        self.assertIsNotNone(sql_composer.validate_fragment("SELECT 1 AS a; DROP TABLE core.accounts", "postgres", {"core.accounts"}))
        self.assertIn("outside this step's inputs", sql_composer.validate_fragment("SELECT * FROM core.secrets", "postgres", {"core.accounts"}))
        self.assertIn("WITH", sql_composer.validate_fragment("WITH x AS (SELECT 1 AS a) SELECT a FROM x", "postgres", set()))

    def test_sixty_plus_step_program_assembles_and_runs(self) -> None:
        count = 65
        steps = [{"name": "step_000", "inputs": ["core.accounts"], "columns": [{"name": "account_id"}, {"name": "account_type"}], "rules": ["active only"]}]
        steps += [{"name": f"step_{index:03d}", "inputs": [f"step_{index - 1:03d}"], "columns": [{"name": "account_id"}, {"name": "account_type"}], "rules": [f"rule {index}"]} for index in range(1, count)]
        plan, errors = sql_composer.normalize_plan({"title": "Deep program", "steps": steps, "final": {"depends_on": [f"step_{count - 1:03d}"]}}, CATALOG)
        self.assertEqual(errors, [])

        def generate(system: str, prompt: str, max_tokens: int) -> str:
            name = step_name(prompt)
            if name == "step_000":
                return "SELECT account_id,\n       account_type\nFROM core.accounts\nWHERE status = 'active'"
            if name == "final":
                return f"SELECT account_type,\n       COUNT(*) AS accounts\nFROM step_{count - 1:03d}\nGROUP BY account_type"
            previous = int(name.split("_")[1]) - 1
            return f"SELECT account_id,\n       account_type\nFROM step_{previous:03d}\nWHERE account_id > {previous}"

        result = sql_composer.build_program(plan, sql_composer.ComposeContext(dialect="postgres", catalog=CATALOG, generate=generate, execute=execute_local, parallelism=4))
        self.assertEqual(result["status"], "completed", result["validation"])
        self.assertEqual(result["sql"].count(" AS (\n"), count)
        self.assertGreater(result["lines"], 6 * count)
        self.assertTrue(check_read_only(result["sql"], "postgres").ok)
        self.assertEqual(result["stats"]["model_calls"], count + 1)
        expected = execute_local("SELECT account_type, COUNT(*) AS accounts FROM core.accounts WHERE status = 'active' GROUP BY account_type")
        self.assertEqual({row["account_type"]: row["accounts"] for row in result["preview"]}, {row["account_type"]: row["accounts"] for row in expected["rows"]})

    def test_non_executable_sources_are_validated_only(self) -> None:
        plan, _ = sql_composer.normalize_plan(TWO_STEP_PLAN, CATALOG)
        result = sql_composer.build_program(plan, sql_composer.ComposeContext(dialect="sqlserver", catalog=CATALOG, generate=lambda system, prompt, tokens: STEP_SQL[step_name(prompt)]))
        self.assertEqual(result["status"], "completed", result["validation"])
        self.assertIsNone(result["execution"])
        self.assertTrue(check_read_only(result["sql"], "sqlserver").ok)

    # ------------------------------------------------------------------ endpoints

    def _route(self, provider_id: str | None) -> None:
        self.client.put("/model-routing", headers=self.headers, json={"assignments": {"sql_composition": provider_id}})

    def test_plan_build_poll_and_save_endpoints(self) -> None:
        provider = self.client.post("/model-providers", headers=self.headers, json={
            "name": f"Fake composer {uuid4().hex[:4]}", "provider_type": "openai_compatible", "base_url": "http://model.invalid/v1", "default_model": "fake", "secret_reference": "env:FAKE_MODEL_KEY",
        }).json()

        def fake_generate(provider, system_prompt, user_prompt, max_tokens, **kwargs):
            if system_prompt == sql_composer.PLAN_SYSTEM:
                # First plan is broken (unknown relation) to exercise the one plan repair.
                return ProviderGenerationResult(content=json.dumps({**TWO_STEP_PLAN, "steps": [{**TWO_STEP_PLAN["steps"][0], "inputs": ["core.ghost"]}, TWO_STEP_PLAN["steps"][1]]}), latency_ms=1)
            if system_prompt == sql_composer.PLAN_REPAIR_SYSTEM:
                return ProviderGenerationResult(content="```json\n" + json.dumps(TWO_STEP_PLAN) + "\n```", latency_ms=1)
            return ProviderGenerationResult(content=STEP_SQL[step_name(user_prompt)], latency_ms=1)

        try:
            self._route(provider["id"])
            with mock.patch("app.routers.sql.generate_text", side_effect=fake_generate):
                planned = self.client.post("/sql/compose/plan", headers=self.headers, json={"spec": "Count active accounts per account type. " * 20, "dialect": "postgres"})
                self.assertEqual(planned.status_code, 200, planned.text)
                body = planned.json()
                self.assertTrue(body["valid"], body["errors"])
                self.assertEqual(body["provider"]["mode"], "plan_repaired")
                self.assertEqual([step["name"] for step in body["plan"]["steps"]], ["active_accounts", "type_counts"])

                invalid = self.client.post("/sql/compose/build", headers=self.headers, json={"plan": {"steps": [{"name": "x", "inputs": ["public.users"]}]}, "dialect": "postgres"})
                self.assertEqual(invalid.status_code, 422)
                self.assertIn("neither a catalogued relation", json.dumps(invalid.json()))

                started = self.client.post("/sql/compose/build", headers=self.headers, json={"plan": body["plan"], "dialect": "postgres", "spec": "Count active accounts per type"})
                self.assertEqual(started.status_code, 202, started.text)
                job_id = started.json()["id"]
                for _ in range(150):
                    detail = self.client.get(f"/sql/compose/{job_id}", headers=self.headers).json()
                    if detail["status"] in ("SUCCEEDED", "FAILED"):
                        break
                    time.sleep(0.1)
            self.assertEqual(detail["status"], "SUCCEEDED", detail)
            result = detail["result"]
            self.assertTrue(result["sql"].startswith("WITH"))
            self.assertEqual(result["validation"]["status"], "passed")
            self.assertEqual({step["name"]: step["status"] for step in result["steps"]}, {"active_accounts": "ok", "type_counts": "ok"})
            self.assertEqual(len(result["preview"]), 2)
            job = self.client.get(f"/jobs/{job_id}", headers=self.headers)
            if job.status_code == 200:
                self.assertTrue(all(item["status"] == "complete" for item in job.json()["plan"]))

            saved = self.client.post("/artifacts", headers=self.headers, json={
                "name": result["title"], "artifact_type": "sql", "content": result["sql"],
                "metadata": {"dialect": "postgres", "question": "Count active accounts per type", "composition": {"plan": detail["plan"], "job_id": job_id, "lines": result["lines"]}},
            })
            self.assertEqual(saved.status_code, 201, saved.text)
            self.assertEqual(self.client.get("/sql/compose/not-a-job", headers=self.headers).status_code, 404)
        finally:
            self._route(None)

    def test_composition_requires_a_real_model(self) -> None:
        local = next((item for item in self.client.get("/model-providers", headers=self.headers).json() if item["provider_type"] == "local_mock"), None)
        if local is None:
            self.skipTest("no local provider seeded")
        try:
            self._route(local["id"])
            response = self.client.post("/sql/compose/plan", headers=self.headers, json={"spec": "Count accounts by type please", "dialect": "postgres"})
            self.assertEqual(response.status_code, 409, response.text)
        finally:
            self._route(None)


if __name__ == "__main__":
    unittest.main()
