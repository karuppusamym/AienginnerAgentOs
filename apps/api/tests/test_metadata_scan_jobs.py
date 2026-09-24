import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-scan-jobs-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("QDRANT_URL", "")
os.environ.setdefault("SUPERSET_INTERNAL_URL", "")
os.environ.setdefault("SUPERSET_ADMIN_PASSWORD", "")
os.environ.setdefault("SUPERSET_EDITOR_SSO_SECRET", "test-editor-secret")
os.environ.setdefault("ENABLE_DEMO_DATA", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import connector_runtime, metadata_scan_runtime
from app.connector_runtime import MetadataDiscovery
from app.database import SessionLocal, engine
from app.main import app
from app.metadata_scan_runtime import MAX_JOB_LOG_ENTRIES, append_job_log, execute_metadata_scan
from app.models import Connector, DataAsset, Job, Project, User

TOOLS = [
    {
        "name": "sqlserver.payments.by_status",
        "description": "Return payments filtered by payment status.",
        "inputSchema": {"type": "object", "properties": {"status": {"type": "string", "description": "settled, pending, or refunded"}}, "required": ["status"]},
        "annotations": {"readOnlyHint": False},
    },
    {"name": "postgres.payments.summary", "description": "Payment summary by status.", "inputSchema": {"type": "object", "properties": {}}},
]


class MetadataScanJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        if database_file.exists():
            database_file.unlink()

    def _admin_id(self) -> str:
        with SessionLocal() as db:
            return db.scalar(select(User.id).where(User.email == "admin@datapilot.local"))

    def _connector_and_job(self, created_at: datetime | None = None, status: str = "QUEUED") -> tuple[str, str]:
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.email == "admin@datapilot.local"))
            project = db.scalar(select(Project).limit(1))
            connector = Connector(project_id=project.id, name=f"Payments MCP {uuid4().hex[:6]}", connector_type="sql_server", connection_mode="mcp", mcp_server_url="http://mcp-toolbox:5000/mcp", read_only=True)
            db.add(connector)
            db.flush()
            job = self._job(db, connector, admin, created_at, status)
            db.commit()
            return connector.id, job.id

    def _job(self, db, connector, admin, created_at=None, status="QUEUED", legacy=False) -> Job:
        job = Job(project_id=connector.project_id, title=f"Metadata scan: {connector.name}", job_type="metadata_scan", status=status, created_by=admin.id,
                  evidence=[{"type": "connector", "label": connector.name, **({} if legacy else {"connector_id": connector.id})}],
                  logs=[{"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Metadata discovery queued"}])
        if created_at:
            job.created_at = created_at
        db.add(job)
        db.flush()
        return job

    def test_identical_consecutive_log_lines_fold_and_the_log_is_capped(self) -> None:
        job = SimpleNamespace(logs=[])
        for _ in range(5):
            append_job_log(job, "error", "[Errno -5] No address associated with hostname")
        self.assertEqual(len(job.logs), 1)
        self.assertEqual(job.logs[0]["repeat"], 5)
        for index in range(MAX_JOB_LOG_ENTRIES * 2):
            append_job_log(job, "info", f"line {index}")
        self.assertLessEqual(len(job.logs), MAX_JOB_LOG_ENTRIES)
        self.assertEqual(job.logs[0]["message"], "[Errno -5] No address associated with hostname")
        self.assertEqual(job.logs[-1]["message"], f"line {MAX_JOB_LOG_ENTRIES * 2 - 1}")

    def test_retried_dns_failure_stays_bounded_and_fails_once_on_the_last_attempt(self) -> None:
        connector_id, job_id = self._connector_and_job()
        failure = OSError("[Errno -5] No address associated with hostname")
        with mock.patch.object(metadata_scan_runtime, "discover_metadata", side_effect=failure):
            for attempt in (1, 2, 3):
                with self.assertRaises(OSError):
                    execute_metadata_scan(connector_id, job_id, self._admin_id(), attempt, 3)
                with SessionLocal() as db:
                    status = db.get(Job, job_id).status
                self.assertEqual(status, "FAILED" if attempt == 3 else "RETRYING")
        with SessionLocal() as db:
            logs = db.get(Job, job_id).logs
        self.assertLessEqual(len(logs), 8)
        self.assertIn("Failed after 3 attempts", logs[-1]["message"])
        self.assertTrue(any("Retrying metadata discovery (attempt 2 of 3)" in entry["message"] for entry in logs))

    def test_successful_scan_supersedes_earlier_failures_of_the_same_connector(self) -> None:
        earlier = datetime.now(timezone.utc) - timedelta(days=30)
        connector_id, job_id = self._connector_and_job()
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.email == "admin@datapilot.local"))
            connector = db.get(Connector, connector_id)
            old_failed = self._job(db, connector, admin, earlier, "FAILED")
            legacy_failed = self._job(db, connector, admin, earlier, "FAILED", legacy=True)
            other = Connector(project_id=connector.project_id, name=f"Other {uuid4().hex[:6]}", connector_type="postgres", read_only=True)
            db.add(other)
            db.flush()
            unrelated = self._job(db, other, admin, earlier, "FAILED")
            db.commit()
            ids = (old_failed.id, legacy_failed.id, unrelated.id)
        discovery = MetadataDiscovery(assets=[], summary={"schemas": 0, "tables": 0, "columns": 0})
        with mock.patch.object(metadata_scan_runtime, "discover_metadata", return_value=discovery):
            result = execute_metadata_scan(connector_id, job_id, self._admin_id(), 1, 3)
        self.assertEqual(result["status"], "SUCCEEDED")
        with SessionLocal() as db:
            statuses = [db.get(Job, item).status for item in ids]
            self.assertIn("Superseded", db.get(Job, ids[0]).logs[-1]["message"])
        self.assertEqual(statuses, ["SUPERSEDED", "SUPERSEDED", "FAILED"])

    def test_mcp_discovery_catalogs_parameters_as_inputs_with_descriptions(self) -> None:
        connector_id, job_id = self._connector_and_job()
        with mock.patch.object(connector_runtime, "list_mcp_tools", return_value=TOOLS):
            with SessionLocal() as db:
                discovery = connector_runtime.discover_mcp_metadata(db.get(Connector, connector_id))
        by_name = {asset["table_name"]: asset for asset in discovery.assets}
        payments = by_name["sqlserver.payments.by_status"]
        self.assertEqual(payments["columns"][0]["role"], "parameter")
        self.assertIn("Input parameter (required): settled", payments["columns"][0]["description"])
        self.assertIn("no-output-schema", payments["tags"])
        self.assertNotIn("input-schema-only", payments["tags"])
        self.assertIn("Parameters: status (string, required).", payments["description_hint"])
        self.assertIn("does not publish output columns", payments["description_hint"])
        self.assertIsNone(payments["row_count"])
        self.assertIn("Takes no parameters.", by_name["postgres.payments.summary"]["description_hint"])

        # A rescan keeps notes people wrote and upgrades the bare description an earlier scan stored.
        with SessionLocal() as db:
            connector = db.get(Connector, connector_id)
            db.add(DataAsset(project_id=connector.project_id, connector_id=connector.id, source_name=connector.name, schema_name="mcp", table_name="sqlserver.payments.by_status",
                             columns=[{"name": "status", "type": "string", "business_name": "Payment status"}], description="Return payments filtered by payment status."))
            db.commit()
        with mock.patch.object(connector_runtime, "list_mcp_tools", return_value=TOOLS), mock.patch.object(metadata_scan_runtime, "discover_metadata", side_effect=lambda item: connector_runtime.discover_mcp_metadata(item)):
            execute_metadata_scan(connector_id, job_id, self._admin_id())
        with SessionLocal() as db:
            asset = db.scalar(select(DataAsset).where(DataAsset.connector_id == connector_id, DataAsset.table_name == "sqlserver.payments.by_status"))
            self.assertEqual(asset.columns[0]["business_name"], "Payment status")
            self.assertIn("Parameters: status", asset.description)


if __name__ == "__main__":
    unittest.main()
