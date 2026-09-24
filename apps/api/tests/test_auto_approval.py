import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-auto-approval-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("QDRANT_URL", "")
os.environ.setdefault("SUPERSET_INTERNAL_URL", "")
os.environ.setdefault("SUPERSET_ADMIN_PASSWORD", "")
os.environ.setdefault("SUPERSET_EDITOR_SSO_SECRET", "test-editor-secret")
os.environ.setdefault("ENABLE_DEMO_DATA", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.main import app
from app.models import Approval, AuditEvent, Job, User

EMBED = {
    "embedded_id": "embed-1", "superset_domain": "http://localhost:8088", "dashboard_id": 1, "dashboard_slug": "datapilot-query-x",
    "dashboard_title": "Auto", "dataset_relation": "staging.dp_query", "superset_dataset_id": 2, "chart_ids": [3], "chart_count": 1,
    "access_mode": "dashboard_scope", "rls_column": None,
}


class AutoApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        token = cls.client.post("/auth/login", json={"email": "admin@datapilot.local", "password": "ChangeMe123!"}).json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {token}"}
        cls.project_id = cls.client.get("/approvals/auto-approval", headers=cls.headers).json()["project_id"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        if database_file.exists():
            database_file.unlink()

    def setUp(self) -> None:
        self._switch(False)

    def _switch(self, enabled: bool) -> None:
        response = self.client.put(f"/projects/{self.project_id}/auto-approval", headers=self.headers, json={"enabled": enabled})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["enabled"], enabled)

    def _request_publication(self, sql: str) -> dict:
        artifact = self.client.post("/artifacts", headers=self.headers, json={"name": f"Query {uuid4().hex[:6]}", "artifact_type": "sql", "content": sql, "metadata": {"dialect": "postgres", "connector_id": None}})
        self.assertEqual(artifact.status_code, 201, artifact.text)
        with mock.patch("app.routers.analytics.superset_availability", return_value={"available": True, "reason": ""}), \
                mock.patch("app.core.get_embed_configuration", return_value=EMBED):
            response = self.client.post("/analytics/publish-sql", headers=self.headers, json={"artifact_id": artifact.json()["id"], "name": "Auto reviewed"})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def _approval(self, approval_id: str) -> Approval:
        with SessionLocal() as db:
            return db.get(Approval, approval_id)

    def _manual_request(self, action_type: str, title: str, risk_level: str = "medium") -> str:
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.email == "admin@datapilot.local"))
            job = Job(project_id=self.project_id, title=title, job_type="agent_run", status="WAITING_FOR_APPROVAL", created_by=admin.id)
            db.add(job)
            db.flush()
            approval = Approval(project_id=self.project_id, job_id=job.id, title=title, action_type=action_type, risk_level=risk_level, requested_by=admin.id, evidence={"summary": title})
            db.add(approval)
            db.commit()
            return approval.id

    def test_read_only_non_pii_publication_is_auto_approved_with_audit(self) -> None:
        self._switch(True)
        result = self._request_publication("SELECT 1 AS value")
        self.assertEqual(result["status"], "auto_approved", result)
        approval = self._approval(result["approval_id"])
        self.assertEqual(approval.status, "approved")
        self.assertIsNone(approval.decided_by)
        self.assertTrue(approval.decision_note.startswith("Auto-approved by policy"))
        self.assertIn("sql_guard: one read-only SELECT", approval.decision_note)
        review = approval.evidence["auto_review"]
        self.assertEqual(review["decision"], "approved")
        self.assertTrue(all(item["passed"] for item in review["checks"]))
        with SessionLocal() as db:
            job = db.get(Job, approval.job_id)
            self.assertEqual(job.status, "SUCCEEDED")
            event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == approval.id, AuditEvent.event_type == "approval.auto_approved"))
        self.assertIsNotNone(event)
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.details["decision"], "approved")

    def test_pii_publication_stays_pending_with_reason(self) -> None:
        self._switch(True)
        result = self._request_publication("SELECT 'a@example.com' AS customer_email")
        self.assertEqual(result["status"], "awaiting_approval")
        approval = self._approval(result["approval_id"])
        self.assertEqual(approval.status, "pending")
        self.assertEqual(approval.evidence["auto_review"]["decision"], "manual")
        self.assertIn("PII", approval.evidence["auto_review"]["reason"])

    def test_write_delete_and_external_requests_stay_with_a_human(self) -> None:
        self._switch(True)
        external = self._manual_request("agent_execution", "Copy all customer records to the marketing shared drive")
        retention = self._manual_request("apply_retention", "Delete 40 expired audit_events records", "high")
        index = self._manual_request("create_index", "Create index on core.accounts")
        response = self.client.post("/approvals/auto-review", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        for approval_id in (external, retention, index):
            approval = self._approval(approval_id)
            self.assertEqual(approval.status, "pending")
            self.assertEqual(approval.evidence["auto_review"]["decision"], "manual")
        self.assertIn("external", self._approval(external).evidence["auto_review"]["reason"])

    def test_switch_off_approves_nothing(self) -> None:
        result = self._request_publication("SELECT 2 AS value")
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertEqual(self.client.post("/approvals/auto-review", headers=self.headers).json(), {"enabled": False, "approved": 0, "manual": 0, "results": []})
        approval = self._approval(result["approval_id"])
        self.assertEqual(approval.status, "pending")
        self.assertNotIn("auto_review", approval.evidence)

    def test_separation_of_duties_keeps_self_requested_publication_manual(self) -> None:
        self._switch(True)
        with mock.patch.dict(os.environ, {"APPROVAL_SEPARATION_OF_DUTIES": "true"}):
            result = self._request_publication("SELECT 3 AS value")
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertIn("Separation of duties", self._approval(result["approval_id"]).evidence["auto_review"]["reason"])


if __name__ == "__main__":
    unittest.main()
