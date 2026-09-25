import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-designer-{uuid4().hex}.db"
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

from app import answer_review
from app.database import SessionLocal, engine
from app.main import app
from app.model_runtime import ProviderGenerationResult
from app.models import AgentDefinition, RouteDecision

JEV = SimpleNamespace(id="jev-test", provider_type="jev", default_model="typesafe/jev-1.13")
TEXT_MODEL = SimpleNamespace(id="llm-test", provider_type="openrouter", default_model="anthropic/claude-sonnet-5")

ANALYSIS = {
    "sql": "SELECT account_type, COUNT(*) AS accounts FROM demo.accounts GROUP BY account_type",
    "grounding": {"catalog_matches": [{"relation": "demo.accounts"}]},
    "provider": {"mode": "model"},
    "validation": {"status": "passed"},
}
EXECUTION = {"columns": ["account_type", "accounts"], "rows": [{"account_type": "Platinum Savings", "accounts": 1234}, {"account_type": "Checking", "accounts": 87}], "row_count": 2}


def _jev_answers(answers_question: float, grounded: float) -> dict:
    return {"ok": True, "answers": {"answers_question": {"noul": answers_question}, "grounded": {"noul": grounded}}, "model": "typesafe/jev-1.13", "latency_ms": 7, "cost_usd": 0.00002, "error": None}


class ReviewerTests(unittest.TestCase):
    def test_good_answer_is_ok_and_jev_never_sees_row_values(self) -> None:
        with mock.patch("app.jev_client.ask", return_value=_jev_answers(0.93, 0.9)) as ask:
            review = answer_review.review_answer(None, JEV, "How many accounts by account type?", ANALYSIS, EXECUTION, "Platinum Savings has 1,234 accounts and Checking has 87.")
        self.assertEqual(review["verdict"], "ok", review)
        self.assertEqual(review["by"], "jev")
        self.assertEqual(review["probabilities"], {"answers_question": 0.93, "grounded": 0.9})
        self.assertTrue(all(check["passed"] for check in review["checks"]))
        state = ask.call_args.args[1]
        self.assertEqual(set(state), {"question", "sql", "columns", "row_count", "narrative"})
        sent = json.dumps(state)
        for value in ("Platinum Savings", "1,234", "1234", "87"):
            self.assertNotIn(value, sent)
        self.assertIn("accounts", state["columns"])
        self.assertEqual(state["row_count"], 2)

    def test_low_answers_question_probability_is_doubtful_with_a_warning(self) -> None:
        with mock.patch("app.jev_client.ask", return_value=_jev_answers(0.1, 0.8)):
            review = answer_review.review_answer(None, JEV, "Which branch opened most loans?", ANALYSIS, EXECUTION, "There are 2 account types.")
        self.assertEqual(review["verdict"], "doubtful")
        self.assertTrue(review["warning"].startswith(answer_review.WARNING_PREFIX))

    def test_execution_error_is_doubtful_without_a_model(self) -> None:
        review = answer_review.review_answer(None, None, "How many accounts?", ANALYSIS, {"columns": [], "rows": [], "row_count": 0, "error": "relation does not exist"}, "No answer.")
        self.assertEqual(review["verdict"], "doubtful")
        self.assertEqual(review["by"], "deterministic")

    def test_invented_figures_and_ungrounded_tables_need_a_check(self) -> None:
        analysis = {**ANALYSIS, "sql": "SELECT account_type, COUNT(*) AS accounts FROM demo.accounts a JOIN demo.secret_table s ON s.id = a.id GROUP BY 1"}
        review = answer_review.review_answer(None, None, "How many accounts by account type?", analysis, EXECUTION, "Platinum Savings has 9,999 accounts.")
        failed = {check["name"] for check in review["checks"] if not check["passed"]}
        self.assertEqual(failed, {"numbers_in_result", "tables_match_grounding"})
        self.assertIn(review["verdict"], {"check", "doubtful"})

    def test_text_model_is_asked_for_json_probabilities(self) -> None:
        reply = ProviderGenerationResult(content='{"answers_question": 0.8, "grounded": 0.9}', latency_ms=5)
        with mock.patch("app.model_runtime.generate_text", return_value=reply), mock.patch("app.jev_client.log_call"):
            review = answer_review.review_answer(None, TEXT_MODEL, "How many accounts by account type?", ANALYSIS, EXECUTION, "Checking has 87 accounts.")
        self.assertEqual(review["by"], "llm")
        self.assertEqual(review["verdict"], "ok")

    def test_any_failure_yields_unreviewed(self) -> None:
        with mock.patch("app.answer_review.review_answer", side_effect=RuntimeError("boom")):
            review = answer_review.review_answer_safely(None, None, None, "q", ANALYSIS, EXECUTION, "a")
        self.assertEqual(review["verdict"], "unreviewed")
        self.assertIn("boom", review["model_error"])


class DesignerApiTests(unittest.TestCase):
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

    def _ask(self, question: str) -> dict:
        conversation = self.client.post("/conversations", headers=self.headers, json={"title": "Review"}).json()["id"]
        response = self.client.post(f"/conversations/{conversation}/messages", headers=self.headers, json={"content": question, "dialect": "postgres"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_chat_answers_carry_a_review_stored_on_the_route_decision(self) -> None:
        message = self._ask("How many accounts by account type?")
        review = message["structured"]["review"]
        self.assertIn(review["verdict"], {"ok", "check", "doubtful"})
        self.assertEqual({check["name"] for check in review["checks"]} >= {"sql_executed", "numbers_in_result", "tables_match_grounding", "not_fallback"}, True)
        with SessionLocal() as db:
            decision = db.scalar(select(RouteDecision).where(RouteDecision.message_id == message["id"]))
            self.assertEqual(decision.outcome["review_verdict"], review["verdict"])

    def test_reviewer_failure_never_breaks_the_answer(self) -> None:
        with mock.patch("app.answer_review.review_answer", side_effect=RuntimeError("reviewer down")):
            message = self._ask("How many accounts by account type?")
        self.assertEqual(message["structured"]["review"]["verdict"], "unreviewed")
        self.assertNotIn(answer_review.WARNING_PREFIX, message["content"])

    def test_seeded_reviewer_agent_is_published(self) -> None:
        agents = {agent["name"]: agent for agent in self.client.get("/agents", headers=self.headers).json()}
        self.assertIn("Reviewer", agents)
        self.assertEqual(agents["Reviewer"]["version_status"], "published")
        self.assertEqual(set(agents["Reviewer"]["tool_names"]), {"catalog.search", "sql.preview"})

    def test_agent_draft_keeps_only_registry_tools(self) -> None:
        reply = ProviderGenerationResult(content=json.dumps({
            "purpose": "Finds stale datasets.", "instructions": "Search the catalog. Report stale tables.", "autonomy_level": 3,
            "tool_names": ["catalog.search", "rm.rf", "shell.exec"],
        }), latency_ms=5)
        with mock.patch("app.agent_designer.design_provider", return_value=TEXT_MODEL), \
                mock.patch("app.agent_designer.generate_text", return_value=reply), \
                mock.patch("app.agent_designer._jev_tool_scores", return_value=(None, None)), \
                mock.patch("app.jev_client.log_call"):
            response = self.client.post("/agents/draft", headers=self.headers, json={"name": "Freshness", "brief": "Find datasets that have not been refreshed."})
        self.assertEqual(response.status_code, 200, response.text)
        draft = response.json()
        self.assertEqual(draft["tool_names"], ["catalog.search"])
        self.assertEqual(set(draft["rejected_tool_names"]), {"rm.rf", "shell.exec"})
        self.assertEqual(draft["purpose"], "Finds stale datasets.")
        self.assertFalse(draft["saved"])
        with SessionLocal() as db:
            self.assertIsNone(db.scalar(select(AgentDefinition).where(AgentDefinition.name == "Freshness")))

    def test_agent_draft_with_jev_scores_rejects_unknown_names(self) -> None:
        verdict = {"by": "jev", "model": "typesafe/jev-1.13", "probabilities": {"lineage.query": 0.6, "ghost.tool": 0.3, "catalog.search": 0.1}, "latency_ms": 5, "cost_usd": 0.00002}
        with mock.patch("app.agent_designer.design_provider", return_value=None), \
                mock.patch("app.agent_designer._jev_tool_scores", return_value=(verdict, None)):
            draft = self.client.post("/agents/draft", headers=self.headers, json={"name": "Lineage", "brief": "Explain upstream lineage."}).json()
        self.assertEqual(draft["tool_names"], ["lineage.query"])
        self.assertEqual(draft["rejected_tool_names"], ["ghost.tool"])
        self.assertEqual(draft["tool_choice"]["by"], "jev")
        self.assertEqual(draft["by"], "template")
        self.assertTrue(draft["purpose"].startswith("Explain upstream lineage"))

    def test_query_tool_draft_only_suggests_real_placeholders(self) -> None:
        sql = "SELECT account_type, COUNT(*) AS total FROM demo.accounts WHERE branch = :branch_code AND opened_year >= :min_year GROUP BY account_type"
        reply = ProviderGenerationResult(content=json.dumps({
            "name": "accounts.count_by_type", "description": "Counts accounts by type for a branch.", "purpose": "Use for branch account mix.",
            "tags": ["Accounts", "branch mix"], "line_of_business": "Retail Banking",
            "parameters": {"branch_code": {"type": "string", "description": "Branch code"}, "min_year": {"type": "integer"}, "evil": {"type": "string"}},
        }), latency_ms=5)
        with mock.patch("app.agent_designer.design_provider", return_value=TEXT_MODEL), \
                mock.patch("app.agent_designer.generate_text", return_value=reply), mock.patch("app.jev_client.log_call"):
            draft = self.client.post("/query-tools/draft", headers=self.headers, json={"sql": sql}).json()
        self.assertEqual(draft["name"], "accounts.count_by_type")
        self.assertEqual(set(draft["parameter_schema"]["properties"]), {"branch_code", "min_year"})
        self.assertEqual(draft["parameter_schema"]["properties"]["min_year"]["type"], "integer")
        self.assertEqual(draft["line_of_business"], "Retail Banking")
        self.assertIn("branch-mix", draft["tags"])
        self.assertEqual(draft["allowed_relations"], ["demo.accounts"])

    def test_query_tool_draft_without_a_model_and_validation(self) -> None:
        with mock.patch("app.agent_designer.design_provider", return_value=None):
            draft = self.client.post("/query-tools/draft", headers=self.headers, json={"question": "Total transaction amount by type"}).json()
        self.assertEqual(draft["by"], "template")
        self.assertEqual(draft["parameter_schema"]["properties"], {})
        self.assertEqual(draft["line_of_business"], "Retail Banking")
        self.assertEqual(self.client.post("/query-tools/draft", headers=self.headers, json={}).status_code, 422)

    def test_agent_created_without_purpose_gets_one(self) -> None:
        base = {"autonomy_level": 2, "tool_names": ["catalog.search"], "instructions": "Search the catalog."}
        reply = ProviderGenerationResult(content='{"purpose": "Watches data freshness and flags late loads."}', latency_ms=5)
        with mock.patch("app.agent_designer.design_provider", return_value=TEXT_MODEL), \
                mock.patch("app.agent_designer.generate_text", return_value=reply), mock.patch("app.jev_client.log_call"):
            created = self.client.post("/agents", headers=self.headers, json={**base, "name": f"Freshness Watch {uuid4().hex[:4]}"})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["purpose"], "Watches data freshness and flags late loads.")
        with mock.patch("app.agent_designer.design_provider", return_value=None):
            fallback = self.client.post("/agents", headers=self.headers, json={**base, "name": f"Backfill {uuid4().hex[:4]}", "purpose": ""})
        self.assertEqual(fallback.status_code, 201, fallback.text)
        self.assertIn("agent handles", fallback.json()["purpose"])
        with mock.patch("app.agent_designer.design_provider", side_effect=RuntimeError("model down")):
            broken = self.client.post("/agents", headers=self.headers, json={**base, "name": f"Resilient {uuid4().hex[:4]}"})
        self.assertEqual(broken.status_code, 201, broken.text)


if __name__ == "__main__":
    unittest.main()
