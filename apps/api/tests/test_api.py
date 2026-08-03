from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import ANY, patch
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-{uuid4().hex}.db"
if database_file.exists():
    database_file.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["QDRANT_URL"] = ""
os.environ["SUPERSET_INTERNAL_URL"] = ""
os.environ["SUPERSET_ADMIN_PASSWORD"] = ""
os.environ["SUPERSET_EDITOR_SSO_SECRET"] = "test-editor-secret"
os.environ["ENABLE_DEMO_DATA"] = "true"

from fastapi.testclient import TestClient

from app.database import SessionLocal, engine
from app.connector_runtime import ConnectorRuntimeError, execute_connector_query, list_mcp_tools, resolve_credentials, test_connection as connector_connection_probe
from app.governance import record_governance_event, record_model_generation
from app.main import app, audit
from app.model_runtime import test_provider as invoke_provider_test
from app.models import SupersetProjectDashboard
from app.superset_client import _build_rls_rules


class DataPilotApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        response = cls.client.post(
            "/auth/login",
            json={"email": "admin@datapilot.local", "password": "ChangeMe123!"},
        )
        cls.token = response.json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        if database_file.exists():
            database_file.unlink()

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    def test_recommendations_are_transparent_and_catalog_grounded(self) -> None:
        recommendations = self.client.get("/recommendations", headers=self.headers)
        self.assertEqual(recommendations.status_code, 200)
        payload = recommendations.json()
        self.assertEqual(payload["strategy"], "catalog_metadata")
        self.assertGreaterEqual(len(payload["suggestions"]), 1)
        self.assertIn("basis", payload["suggestions"][0])

    def test_health_probes_and_response_hardening(self) -> None:
        response = self.client.get("/health/live", headers={"X-Request-ID": "release-check:42"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertEqual(response.headers["X-Request-ID"], "release-check:42")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(response.headers["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertEqual(self.client.get("/health/ready").json()["status"], "ready")

        unsafe = self.client.get("/health/live", headers={"X-Request-ID": "unsafe\r\nvalue"})
        self.assertEqual(unsafe.status_code, 200)
        self.assertNotEqual(unsafe.headers["X-Request-ID"], "unsafe\r\nvalue")

    def test_security_overview_returns_dashboard_payload(self) -> None:
        response = self.client.get("/security-overview", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["period"]["key"], "1d")
        self.assertEqual(payload["period"]["label"], "Past 1 day")
        self.assertIn("overall_security_score", payload["overview"])
        self.assertIn("blocked_requests", payload["overview"])
        self.assertEqual(len(payload["event_series"]), 8)
        self.assertEqual(
            [item["category"] for item in payload["events_by_category"]],
            ["Prompt Injection", "PII Exposure", "Toxic Content"],
        )
        self.assertEqual(
            [item["category"] for item in payload["top_security_risks"]],
            ["Prompt Injection", "PII Exposure", "Toxic Content"],
        )

    def test_embedded_analytics_reports_missing_local_service(self) -> None:
        response = self.client.get("/analytics/config", headers=self.headers)
        self.assertEqual(response.status_code, 503)

    def test_embedded_analytics_requires_a_queryable_project_dataset(self) -> None:
        original_project = next(
            item for item in self.client.get("/projects", headers=self.headers).json() if item["is_current"]
        )
        project = self.client.post(
            "/projects",
            headers=self.headers,
            json={"name": "Empty analytics", "description": "No local datasets yet", "environment": "local"},
        )
        self.assertEqual(project.status_code, 201)
        project_id = project.json()["id"]
        selected = self.client.post(f"/projects/{project_id}/select", headers=self.headers)
        self.assertEqual(selected.status_code, 200)
        response = self.client.get("/analytics/config", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertIn("before opening Superset", response.json()["detail"])
        restored = self.client.post(f"/projects/{original_project['id']}/select", headers=self.headers)
        self.assertEqual(restored.status_code, 200)

    def test_embedded_analytics_uses_the_current_project_dataset_mapping(self) -> None:
        projects = self.client.get("/projects", headers=self.headers).json()
        seeded_project = next(item for item in projects if item["slug"] == "retail-banking")
        selected = self.client.post(f"/projects/{seeded_project['id']}/select", headers=self.headers)
        self.assertEqual(selected.status_code, 200)
        with patch(
            "app.main.get_embed_configuration",
            return_value={
                "embedded_id": "embed-1",
                "superset_domain": "http://localhost:8088",
                "dashboard_id": 12,
                "dashboard_slug": "datapilot-project-retail-banking",
                "dashboard_title": "Retail banking analytics",
                "dataset_relation": "core.accounts",
                "superset_dataset_id": 77,
                "chart_ids": [101, 102, 103, 104],
                "chart_count": 4,
                "access_mode": "dashboard_scope",
                "rls_column": None,
            },
        ) as mocked:
            response = self.client.get("/analytics/config", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["embedded_id"], "embed-1")
        self.assertEqual(response.json()["chart_count"], 4)
        self.assertEqual(response.json()["access_mode"], "dashboard_scope")
        mocked.assert_called_once()
        args = mocked.call_args.args
        self.assertEqual(args[0], seeded_project["name"])
        self.assertEqual(args[1], seeded_project["slug"])
        self.assertTrue(args[2]["schema_name"])
        self.assertTrue(args[2]["table_name"])
        self.assertIn("columns", args[2])
        with SessionLocal() as db:
            state = db.query(SupersetProjectDashboard).filter_by(project_id=seeded_project["id"]).one()
            self.assertEqual(state.dashboard_id, 12)
            self.assertEqual(state.dashboard_slug, "datapilot-project-retail-banking")
            self.assertEqual(state.superset_dataset_id, 77)
            self.assertEqual(state.chart_ids, [101, 102, 103, 104])

    def test_guest_rls_rules_are_created_for_project_scoped_columns(self) -> None:
        rls, access_mode, rls_column = _build_rls_rules(
            {
                "project_id": "project-123",
                "project_slug": "retail-banking",
                "columns": [
                    {"name": "project_id", "type": "uuid"},
                    {"name": "account_type", "type": "varchar"},
                ],
            },
            55,
        )
        self.assertEqual(access_mode, "guest_token_project_rls")
        self.assertEqual(rls_column, "project_id")
        self.assertEqual(rls, [{"clause": "project_id = 'project-123'", "dataset": 55}])

    def test_admin_can_create_short_lived_editor_session(self) -> None:
        response = self.client.post("/analytics/editor-session", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("/datapilot/editor-login?token=", payload["url"])
        self.assertEqual(payload["expires_in"], 30)

    def test_connector_secret_json_is_resolved_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"TEST_SQL_CREDENTIALS": '{"username":"reader","password":"private"}'},
        ):
            credentials = resolve_credentials("env:TEST_SQL_CREDENTIALS")
        self.assertEqual(credentials["username"], "reader")
        self.assertEqual(credentials["password"], "private")

    def test_mcp_connector_dispatches_to_a_named_upstream_tool(self) -> None:
        connector = SimpleNamespace(
            id="mcp-connector-1",
            project_id="project-1",
            connector_type="oracle",
            connection_mode="mcp",
            mcp_server_url="http://toolbox.internal:5000/mcp",
            secret_reference=None,
            host=None,
        )
        with patch("app.connector_runtime.list_mcp_tools", return_value=[{"name": "get_account"}]):
            probe = connector_connection_probe(connector)
        self.assertEqual(probe.status, "healthy")
        self.assertIn("1 tools available", probe.message)

        expected = {
            "columns": ["account_id"],
            "rows": [{"account_id": 42}],
            "row_count": 1,
            "truncated": False,
            "limit": 10,
            "duration_ms": 1,
        }
        with patch("app.connector_runtime.execute_mcp_tool", return_value=expected) as invoke:
            result = execute_connector_query(
                connector,
                "SELECT account_id FROM accounts WHERE account_id = :account_id",
                {"account_id": 42},
                10,
                15,
                upstream_tool_name="get_account",
            )
        self.assertEqual(result["rows"], [{"account_id": 42}])
        self.assertEqual(invoke.call_args.args[1], "get_account")
        self.assertEqual(invoke.call_args.args[2], {"account_id": 42})

    def test_mcp_http_handshake_propagates_the_session_id(self) -> None:
        class FakeResponse:
            def __init__(self, payload, status_code=200, headers=None):
                self._payload = payload
                self.status_code = status_code
                self.headers = headers or {"content-type": "application/json"}
                self.text = ""

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

            def json(self):
                return self._payload

        class FakeClient:
            def __init__(self):
                self.calls = []
                self.responses = [
                    FakeResponse(
                        {"jsonrpc": "2.0", "id": "datapilot-initialize", "result": {}},
                        headers={
                            "content-type": "application/json",
                            "mcp-session-id": "session-42",
                        },
                    ),
                    FakeResponse({}, status_code=202),
                    FakeResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": "datapilot-call",
                            "result": {"tools": [{"name": "get_account"}]},
                        }
                    ),
                ]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def post(self, url, headers, json):
                self.calls.append({"url": url, "headers": headers, "json": json})
                return self.responses.pop(0)

        connector = SimpleNamespace(
            mcp_server_url="http://toolbox.internal:5000/mcp",
            secret_reference=None,
        )
        fake_client = FakeClient()
        with patch("app.connector_runtime.httpx.Client", return_value=fake_client):
            tools = list_mcp_tools(connector)
        self.assertEqual(tools, [{"name": "get_account"}])
        self.assertEqual(fake_client.calls[0]["json"]["method"], "initialize")
        self.assertEqual(fake_client.calls[1]["json"]["method"], "notifications/initialized")
        self.assertEqual(fake_client.calls[2]["json"]["method"], "tools/list")
        self.assertEqual(fake_client.calls[2]["headers"]["Mcp-Session-Id"], "session-42")

    def test_mcp_connector_and_query_tool_contract(self) -> None:
        missing_url = self.client.post(
            "/connectors",
            headers=self.headers,
            json={
                "name": "Invalid MCP Oracle",
                "connector_type": "oracle",
                "connection_mode": "mcp",
                "read_only": True,
            },
        )
        self.assertEqual(missing_url.status_code, 400)
        connector = self.client.post(
            "/connectors",
            headers=self.headers,
            json={
                "name": "Governed Oracle Toolbox",
                "connector_type": "oracle",
                "connection_mode": "mcp",
                "mcp_server_url": "http://mcp-toolbox:5000/mcp",
                "read_only": True,
            },
        )
        self.assertEqual(connector.status_code, 201)
        self.assertEqual(connector.json()["connection_mode"], "mcp")
        payload = {
            "name": "accounts.mcp_lookup",
            "description": "Look up one governed account.",
            "purpose": "Retrieve an account for customer servicing.",
            "data_source": "Oracle CUSTOMER",
            "line_of_business": "Retail Banking",
            "owner": "Account Operations",
            "tags": ["Accounts", "Customer-Service", "accounts"],
            "connector_id": connector.json()["id"],
            "sql_template": "SELECT account_id FROM accounts WHERE account_id = :account_id",
            "parameter_schema": {
                "type": "object",
                "required": ["account_id"],
                "properties": {"account_id": {"type": "integer"}},
                "additionalProperties": False,
            },
            "allowed_relations": ["accounts"],
        }
        missing_name = self.client.post("/query-tools", headers=self.headers, json=payload)
        self.assertEqual(missing_name.status_code, 400)
        created = self.client.post(
            "/query-tools",
            headers=self.headers,
            json={**payload, "upstream_tool_name": "get_account"},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["tags"], ["accounts", "customer-service"])

    def test_generic_governance_event_excludes_sensitive_metadata(self) -> None:
        captured = []

        class CaptureAdapter:
            def initialize(self) -> bool:
                return True

            def record_event(self, event) -> None:
                captured.append(event)

        with patch("app.governance._adapters", return_value=[CaptureAdapter()]):
            record_governance_event(
                "tool_execution",
                "catalog.search",
                "succeeded",
                project_id="project-1",
                user_id="user-1",
                session_id="session-1",
                duration_ms=12,
                token="must-not-export",
                sql="SELECT secret_value FROM sensitive_table",
            )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].tenant_id, "project-1")
        self.assertEqual(captured[0].user_id, "user-1")
        self.assertEqual(captured[0].session_id, "session-1")
        self.assertEqual(captured[0].feature, "catalog.search")
        self.assertEqual(captured[0].metadata, {"duration_ms": 12})

    def test_audit_actions_are_exported_to_governance(self) -> None:
        captured = []
        stored = []

        class CaptureAdapter:
            def initialize(self) -> bool:
                return True

            def record_event(self, event) -> None:
                captured.append(event)

        with patch("app.main.current_membership", return_value=SimpleNamespace(project_id="project-1")):
            with patch("app.governance._adapters", return_value=[CaptureAdapter()]):
                audit(
                    SimpleNamespace(add=stored.append),
                    SimpleNamespace(id="user-1"),
                    "artifact.saved",
                    "artifact",
                    "artifact-1",
                    {"version": 3, "content": "must-not-export"},
                )
        self.assertEqual(len(stored), 1)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].event_type, "audit_event")
        self.assertEqual(captured[0].name, "artifact.saved")
        self.assertEqual(captured[0].project_id, "project-1")
        self.assertEqual(captured[0].metadata["entity_type"], "artifact")
        self.assertEqual(captured[0].metadata["detail.version"], 3)
        self.assertNotIn("detail.content", captured[0].metadata)

    def test_http_request_lifecycle_is_exported(self) -> None:
        with patch("app.main.record_governance_event") as recorded:
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        recorded.assert_called_once_with(
            "http_request",
            "GET /health",
            "succeeded",
            session_id=response.headers["X-Request-ID"],
            method="GET",
            path="/health",
            status_code=200,
            duration_ms=ANY,
        )

    def test_local_provider_test_is_exported_as_model_generation(self) -> None:
        provider = SimpleNamespace(provider_type="local_mock", default_model="local-deterministic")
        with patch("app.model_runtime.record_model_generation") as recorded:
            result = invoke_provider_test(provider)
        self.assertEqual(result.status, "healthy")
        recorded.assert_called_once_with(
            feature="provider_test",
            model="local-deterministic",
            provider_type="local_mock",
            input_tokens=4,
            output_tokens=4,
            latency_ms=1,
            input_text='[{"role":"user","content":"Reply with OK only."}]',
            output_text="OK",
        )

    def test_model_generation_exports_measured_latency(self) -> None:
        captured = []

        class CaptureAdapter:
            def initialize(self) -> bool:
                return True

            def record_generation(self, generation) -> None:
                captured.append(generation)

        with patch("app.governance._adapters", return_value=[CaptureAdapter()]):
            record_model_generation(
                feature="sql_generation",
                model="test-model",
                provider_type="test",
                input_tokens=10,
                output_tokens=20,
                latency_ms=345,
                business_id="project-1",
                session_id="session-1",
                user_id="user-1",
            )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].latency_ms, 345)
        self.assertEqual(captured[0].tenant_id, "project-1")
        self.assertEqual(captured[0].user_id, "user-1")
        self.assertEqual(captured[0].session_id, "session-1")

    def test_model_generation_content_capture_is_gated_and_redacted(self) -> None:
        captured = []

        class CaptureAdapter:
            def initialize(self) -> bool:
                return True

            def record_generation(self, generation) -> None:
                captured.append(generation)

        with patch("app.governance._adapters", return_value=[CaptureAdapter()]):
            with patch.dict(os.environ, {"AGENTGUARD_CAPTURE_CONTENT": "false"}):
                record_model_generation(
                    feature="sql_generation",
                    model="test-model",
                    provider_type="test",
                    input_tokens=10,
                    output_tokens=20,
                    input_text="password=private-value",
                    output_text="SELECT 1",
                )
            with patch.dict(
                os.environ,
                {"AGENTGUARD_CAPTURE_CONTENT": "true", "TEST_SECRET_TOKEN": "private-value"},
            ):
                record_model_generation(
                    feature="sql_generation",
                    model="test-model",
                    provider_type="test",
                    input_tokens=10,
                    output_tokens=20,
                    input_text="password=private-value",
                    output_text="Result private-value",
                )
        self.assertIsNone(captured[0].input_text)
        self.assertIsNone(captured[0].output_text)
        self.assertEqual(captured[1].input_text, "password=[REDACTED]")
        self.assertEqual(captured[1].output_text, "Result [REDACTED]")

    def test_agentguard_runtime_skips_non_llm_events_when_infra_spans_are_off(self) -> None:
        from app.agentguard_runtime import record_agentguard_event

        tracks: list[tuple[str, dict[str, object]]] = []

        class _Scope:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_agentguard = ModuleType("agentguard")
        fake_agentguard.is_enabled = lambda: True
        fake_agentguard.context = lambda **kwargs: _Scope()
        fake_agentguard.track = lambda name, **attrs: tracks.append((name, attrs)) or _Scope()

        with patch.dict(sys.modules, {"agentguard": fake_agentguard}):
            with patch.dict(
                os.environ,
                {"AGENTGUARD_ENABLED": "true", "AGENTGUARD_INCLUDE_INFRA_SPANS": "false"},
                clear=False,
            ):
                record_agentguard_event(
                    event_type="tool_execution",
                    name="connector.query",
                    outcome="succeeded",
                    business_id="project-1",
                    session_id="session-1",
                )
            self.assertEqual(tracks, [])

            with patch.dict(
                os.environ,
                {
                    "AGENTGUARD_ENABLED": "true",
                    "AGENTGUARD_INCLUDE_INFRA_SPANS": "false",
                    "AGENTGUARD_EXPORT_GOVERNANCE_EVENTS": "true",
                },
                clear=False,
            ):
                record_agentguard_event(
                    event_type="tool_execution",
                    name="connector.query",
                    outcome="succeeded",
                    business_id="project-1",
                    session_id="session-1",
                )
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0][0], "connector.query")
        self.assertEqual(tracks[0][1]["event_type"], "tool_execution")
        self.assertEqual(tracks[0][1]["outcome"], "succeeded")

    def test_agentguard_runtime_still_exports_llm_content_when_infra_spans_are_off(self) -> None:
        from app.agentguard_runtime import record_model_generation

        generations: list[dict[str, object]] = []

        class _Scope:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_agentguard = ModuleType("agentguard")
        fake_agentguard.is_enabled = lambda: True
        fake_agentguard.context = lambda **kwargs: _Scope()
        fake_agentguard.record_generation = lambda **payload: generations.append(payload)

        with patch.dict(sys.modules, {"agentguard": fake_agentguard}):
            with patch.dict(
                os.environ,
                {
                    "AGENTGUARD_ENABLED": "true",
                    "AGENTGUARD_CAPTURE_CONTENT": "true",
                    "AGENTGUARD_INCLUDE_INFRA_SPANS": "false",
                },
                clear=False,
            ):
                record_model_generation(
                    feature="sql_generation",
                    model="test-model",
                    provider_type="openai",
                    input_tokens=12,
                    output_tokens=18,
                    input_text='[{"role":"user","content":"hello"}]',
                    output_text="world",
                    business_id="project-1",
                    session_id="session-1",
                    user_id="user-1",
                )
        self.assertEqual(len(generations), 1)
        self.assertEqual(generations[0]["input"], '[{"role":"user","content":"hello"}]')
        self.assertEqual(generations[0]["output"], "world")
        self.assertEqual(generations[0]["feature"], "sql_generation")

    def test_connector_query_failure_emits_failed_governance_event(self) -> None:
        captured = []

        class CaptureAdapter:
            def initialize(self) -> bool:
                return True

            def record_event(self, event) -> None:
                captured.append(event)

        connector = SimpleNamespace(
            id="connector-1",
            project_id="project-1",
            connector_type="unsupported",
            secret_reference="env:TEST_SQL_CREDENTIALS",
            host="warehouse.example.local",
            database="warehouse",
        )

        with patch("app.connector_runtime.resolve_credentials", return_value={"username": "reader", "password": "private"}):
            with patch("app.governance._adapters", return_value=[CaptureAdapter()]):
                with self.assertRaises(ConnectorRuntimeError):
                    execute_connector_query(
                        connector,
                        "SELECT 1",
                        {},
                        10,
                        10,
                        user_id="user-1",
                        session_id="session-1",
                        feature="connector_query",
                    )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].event_type, "connector_query")
        self.assertEqual(captured[0].outcome, "failed")
        self.assertEqual(captured[0].tenant_id, "project-1")
        self.assertEqual(captured[0].user_id, "user-1")
        self.assertEqual(captured[0].session_id, "session-1")
        self.assertEqual(captured[0].feature, "connector_query")
        self.assertEqual(captured[0].metadata["read_only"], True)
        self.assertEqual(captured[0].metadata["error_type"], "ConnectorRuntimeError")

    def test_live_connector_test_fails_when_secret_is_missing(self) -> None:
        created = self.client.post(
            "/connectors",
            headers=self.headers,
            json={
                "name": "Unconfigured SQL Server",
                "connector_type": "sql_server",
                "host": "sql.example.local",
                "database": "warehouse",
                "secret_reference": "env:DOES_NOT_EXIST",
                "read_only": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        tested = self.client.post(
            f"/connectors/{created.json()['id']}/test", headers=self.headers
        )
        self.assertEqual(tested.status_code, 400)
        self.assertIn("DOES_NOT_EXIST", tested.json()["detail"])

    def test_connector_description_can_be_updated_and_deleted(self) -> None:
        created = self.client.post(
            "/connectors",
            headers=self.headers,
            json={
                "name": "Finance Oracle",
                "connector_type": "oracle",
                "description": "Finance-owned read-only warehouse connection",
                "host": "oracle.example.local",
                "database": "FIN",
                "secret_reference": "env:FINANCE_ORACLE",
                "read_only": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["description"], "Finance-owned read-only warehouse connection")
        updated = self.client.put(
            f"/connectors/{created.json()['id']}",
            headers=self.headers,
            json={
                "name": "Finance Oracle Warehouse",
                "connector_type": "oracle",
                "description": "Curated finance data, read-only",
                "host": "oracle.example.local",
                "database": "FIN",
                "secret_reference": "env:FINANCE_ORACLE",
                "read_only": True,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Finance Oracle Warehouse")
        self.assertEqual(updated.json()["description"], "Curated finance data, read-only")
        deleted = self.client.delete(f"/connectors/{created.json()['id']}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["status"], "deleted")

    def test_postgres_connector_type_is_registered_with_postgres_dialect(self) -> None:
        created = self.client.post(
            "/connectors", headers=self.headers,
            json={
                "name": "Finance warehouse",
                "connector_type": "postgres",
                "host": "warehouse.internal",
                "database": "finance",
                "secret_reference": "env:POSTGRES_CREDENTIALS",
                "read_only": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["connector_type"], "postgres")
        generated = self.client.post(
            "/sql/generate", headers=self.headers,
            json={"question": "Show finance summary", "dialect": "sqlserver", "connector_id": created.json()["id"]},
        )
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json()["dialect"], "postgres")

    def test_viewer_cannot_see_connector_secret_or_write_conversations(self) -> None:
        email = "readonly.viewer@datapilot.local"
        password = "Temporary123!"
        created_user = self.client.post(
            "/admin/users",
            headers=self.headers,
            json={
                "name": "Readonly Viewer",
                "email": email,
                "temporary_password": password,
                "role": "viewer",
            },
        )
        self.assertEqual(created_user.status_code, 201)
        connector = self.client.post(
            "/connectors",
            headers=self.headers,
            json={
                "name": "Restricted Warehouse",
                "connector_type": "sql_server",
                "host": "warehouse.internal",
                "database": "governed",
                "secret_reference": "env:RESTRICTED_WAREHOUSE",
                "read_only": True,
            },
        )
        self.assertEqual(connector.status_code, 201)
        current_project = next(item for item in self.client.get("/projects", headers=self.headers).json() if item["is_current"])
        membership = self.client.post(
            f"/projects/{current_project['id']}/members",
            headers=self.headers,
            json={"user_id": created_user.json()["id"], "role": "viewer"},
        )
        self.assertEqual(membership.status_code, 200)
        login = self.client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(login.status_code, 200)
        viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        selected = self.client.post(f"/projects/{current_project['id']}/select", headers=viewer_headers)
        self.assertEqual(selected.status_code, 200)

        connectors = self.client.get("/connectors", headers=viewer_headers)
        self.assertEqual(connectors.status_code, 200)
        restricted = next(item for item in connectors.json() if item["name"] == "Restricted Warehouse")
        self.assertNotIn("secret_reference", restricted)

        blocked = self.client.post(
            "/conversations",
            headers=viewer_headers,
            json={"title": "Read-only analysis"},
        )
        self.assertEqual(blocked.status_code, 403)

    def test_demo_connector_scan_indexes_seeded_catalog(self) -> None:
        connectors = self.client.get("/connectors", headers=self.headers).json()
        demo = next(item for item in connectors if item["host"] == "mock-sqlserver")
        scanned = self.client.post(f"/connectors/{demo['id']}/scan", headers=self.headers)
        self.assertEqual(scanned.status_code, 200)
        self.assertEqual(scanned.json()["status"], "SUCCEEDED")
        self.assertGreaterEqual(scanned.json()["summary"]["tables"], 3)

    def test_seeded_catalog_and_overview(self) -> None:
        catalog = self.client.get("/datasets", headers=self.headers)
        overview = self.client.get("/overview", headers=self.headers)
        self.assertEqual(catalog.status_code, 200)
        self.assertGreaterEqual(len(catalog.json()), 3)
        self.assertGreaterEqual(overview.json()["counts"]["data_assets"], 3)

    def test_sql_generation_is_read_only(self) -> None:
        response = self.client.post(
            "/sql/generate",
            headers=self.headers,
            json={"question": "Show monthly deposit growth", "dialect": "sqlserver"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["validation"]["read_only"])
        self.assertIn("core.accounts", result["sql"])
        self.assertEqual(result["provider"]["mode"], "deterministic_local")
        self.assertEqual(result["provider"]["model"], "datapilot-mock-v1")

    def test_controlled_agent_run_creates_approval(self) -> None:
        response = self.client.post(
            "/agents/runs",
            headers=self.headers,
            json={
                "objective": "Schedule a daily customer quality workflow",
                "autonomy_level": 3,
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "WAITING_FOR_APPROVAL")
        self.assertIsNotNone(response.json()["approval_id"])

    def test_file_staging_creates_queryable_relation(self) -> None:
        response = self.client.post(
            "/files/ingest",
            headers=self.headers,
            data={"stage_to_postgres": "true"},
            files={
                "file": (
                    "transactions_test.csv",
                    b"transaction_id,amount,channel\n1,10.5,card\n2,20.0,mobile\n",
                    "text/csv",
                )
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], "staged")
        relation = payload["profile"]["staged_table"]["relation"]
        query = self.client.post(
            "/sql/execute",
            headers=self.headers,
            json={"sql": f"SELECT COUNT(*) AS row_count FROM {relation}", "dialect": "postgres"},
        )
        self.assertEqual(query.status_code, 200)
        self.assertEqual(query.json()["rows"][0]["row_count"], 2)

    def test_mapped_ingestion_and_quality_quarantine(self) -> None:
        uploaded = self.client.post(
            "/files/ingest",
            headers=self.headers,
            data={"stage_to_postgres": "false"},
            files={
                "file": (
                    "mapped_quality.csv",
                    b"transaction_id,amount,channel\n1,10.5,card\n2,20.0,\n3,15.0,mobile\n",
                    "text/csv",
                )
            },
        ).json()
        mapping = self.client.post(
            f"/files/{uploaded['id']}/schema",
            headers=self.headers,
            json={
                "name": "Mapped transaction ingestion",
                "target_table": "mapped_transactions",
                "columns": [
                    {"source_name": "transaction_id", "target_name": "event_id", "target_type": "integer", "nullable": False},
                    {"source_name": "amount", "target_name": "amount", "target_type": "number", "nullable": False},
                    {"source_name": "channel", "target_name": "channel", "target_type": "string", "nullable": True},
                ],
            },
        )
        self.assertEqual(mapping.status_code, 201)
        staged = self.client.post(
            f"/files/{uploaded['id']}/stage",
            headers=self.headers,
            json={"mapping_id": mapping.json()["id"]},
        )
        self.assertEqual(staged.status_code, 201)
        staged_payload = staged.json()
        relation = staged_payload["profile"]["staged_table"]["relation"]
        self.assertEqual(staged_payload["mapping"]["run_count"], 1)
        count = self.client.post(
            "/sql/execute",
            headers=self.headers,
            json={"sql": f"SELECT COUNT(*) AS row_count FROM {relation}", "dialect": "postgres"},
        )
        self.assertEqual(count.json()["rows"][0]["row_count"], 3)
        repeated = self.client.post(
            f"/files/{uploaded['id']}/stage",
            headers=self.headers,
            json={"mapping_id": mapping.json()["id"]},
        )
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(repeated.json()["mapping"]["run_count"], 2)
        self.assertNotEqual(repeated.json()["profile"]["staged_table"]["relation"], relation)
        suggested = self.client.post(
            f"/quality/assets/{staged_payload['asset_id']}/suggest", headers=self.headers
        )
        self.assertEqual(suggested.status_code, 201)
        self.assertGreaterEqual(len(suggested.json()), 1)

        rule = self.client.post(
            "/quality/rules",
            headers=self.headers,
            json={
                "asset_id": staged_payload["asset_id"],
                "name": "channel is not null",
                "rule_type": "not_null",
                "column_name": "channel",
                "config": {},
                "severity": "error",
            },
        )
        self.assertEqual(rule.status_code, 201)
        quality_run = self.client.post(
            f"/quality/rules/{rule.json()['id']}/run", headers=self.headers
        )
        self.assertEqual(quality_run.status_code, 201)
        self.assertEqual(quality_run.json()["status"], "failed", quality_run.json())
        self.assertEqual(quality_run.json()["failed_rows"], 1)
        quarantine = quality_run.json()["quarantine_relation"]
        quarantined = self.client.post(
            "/sql/execute",
            headers=self.headers,
            json={"sql": f"SELECT COUNT(*) AS row_count FROM {quarantine}", "dialect": "postgres"},
        )
        self.assertEqual(quarantined.json()["rows"][0]["row_count"], 1)

    def test_stable_append_merge_and_replace_load_modes(self) -> None:
        uploaded = self.client.post(
            "/files/ingest",
            headers=self.headers,
            data={"stage_to_postgres": "false"},
            files={
                "file": (
                    "stable_modes.csv",
                    b"event_id,amount\n1,10.5\n2,20.0\n",
                    "text/csv",
                )
            },
        ).json()
        mapping = self.client.post(
            f"/files/{uploaded['id']}/schema",
            headers=self.headers,
            json={
                "name": "Stable load modes",
                "target_table": "stable_mode_events",
                "columns": [
                    {"source_name": "event_id", "target_name": "event_id", "target_type": "integer", "nullable": False},
                    {"source_name": "amount", "target_name": "amount", "target_type": "number", "nullable": False},
                ],
            },
        ).json()

        first = self.client.post(
            f"/files/{uploaded['id']}/stage",
            headers=self.headers,
            json={"mapping_id": mapping["id"], "load_mode": "append"},
        ).json()
        second = self.client.post(
            f"/files/{uploaded['id']}/stage",
            headers=self.headers,
            json={"mapping_id": mapping["id"], "load_mode": "append"},
        ).json()
        self.assertEqual(first["profile"]["staged_table"]["relation"], second["profile"]["staged_table"]["relation"])
        self.assertEqual(second["profile"]["staged_table"]["row_count"], 4)

        merged = self.client.post(
            f"/files/{uploaded['id']}/stage",
            headers=self.headers,
            json={"mapping_id": mapping["id"], "load_mode": "upsert", "key_columns": ["event_id"]},
        ).json()
        self.assertEqual(merged["profile"]["staged_table"]["row_count"], 2)
        self.assertEqual(merged["profile"]["staged_table"]["replaced_rows"], 4)

        replaced = self.client.post(
            f"/files/{uploaded['id']}/stage",
            headers=self.headers,
            json={"mapping_id": mapping["id"], "load_mode": "replace"},
        ).json()
        self.assertEqual(replaced["profile"]["staged_table"]["row_count"], 2)
        self.assertEqual(replaced["profile"]["staged_table"]["load_mode"], "replace")

    def test_approved_incremental_schedule_uses_watermark(self) -> None:
        uploaded = self.client.post(
            "/files/ingest",
            headers=self.headers,
            data={"stage_to_postgres": "false"},
            files={"file": ("incremental.csv", b"event_id,updated_at\n1,2026-01-01T00:00:00\n2,2026-01-02T00:00:00\n", "text/csv")},
        ).json()
        mapping = self.client.post(
            f"/files/{uploaded['id']}/schema",
            headers=self.headers,
            json={
                "name": "Incremental events",
                "target_table": "scheduled_incremental_events",
                "columns": [
                    {"source_name": "event_id", "target_name": "event_id", "target_type": "integer", "nullable": False},
                    {"source_name": "updated_at", "target_name": "updated_at", "target_type": "string", "nullable": False},
                ],
            },
        ).json()
        scheduled = self.client.post(
            "/schedules",
            headers=self.headers,
            json={
                "name": "Incremental event refresh",
                "mapping_id": mapping["id"],
                "cron": "0 * * * *",
                "load_mode": "upsert",
                "key_columns": ["event_id"],
                "watermark_column": "updated_at",
            },
        )
        self.assertEqual(scheduled.status_code, 201)
        approval = self.client.post(
            f"/approvals/{scheduled.json()['approval_id']}/decision",
            headers=self.headers,
            json={"decision": "approved", "note": "Approved for local test"},
        )
        self.assertTrue(approval.json()["schedule_enabled"])
        first = self.client.post(f"/schedules/{scheduled.json()['id']}/run", headers=self.headers)
        second = self.client.post(f"/schedules/{scheduled.json()['id']}/run", headers=self.headers)
        self.assertEqual(first.json()["loaded_rows"], 2)
        self.assertEqual(second.json()["loaded_rows"], 0)
        self.assertEqual(first.json()["last_watermark"], "2026-01-02T00:00:00")

    def test_artifact_review_comments_and_diff(self) -> None:
        first = self.client.post(
            "/artifacts",
            headers=self.headers,
            json={"name": "Reviewed SQL", "artifact_type": "sql", "content": "SELECT 1", "metadata": {}},
        ).json()
        self.client.post(
            "/artifacts",
            headers=self.headers,
            json={"artifact_id": first["id"], "name": "Reviewed SQL", "artifact_type": "sql", "content": "SELECT 2", "metadata": {}},
        )
        difference = self.client.get(
            f"/artifacts/{first['id']}/diff?from_version=1&to_version=2", headers=self.headers
        )
        self.assertIn("-SELECT 1", difference.json()["diff"])
        comment = self.client.post(
            f"/artifacts/{first['id']}/comments",
            headers=self.headers,
            json={"body": "Validated locally", "version": 2},
        )
        self.assertEqual(comment.status_code, 201)
        review = self.client.post(
            f"/artifacts/{first['id']}/review",
            headers=self.headers,
            json={"decision": "approved", "note": "Ready for reuse"},
        )
        self.assertEqual(review.json()["status"], "approved")
        comments = self.client.get(f"/artifacts/{first['id']}/comments", headers=self.headers)
        self.assertEqual(len(comments.json()), 2)

    def test_evaluation_replay_records_score_and_artifact(self) -> None:
        created = self.client.post(
            "/evaluations",
            headers=self.headers,
            json={
                "name": "Account SQL baseline",
                "description": "Grounding regression",
                "cases": [{
                    "name": "Account growth",
                    "question": "Show account growth",
                    "dialect": "postgres",
                    "expected_tables": ["core.accounts"],
                    "required_sql_tokens": ["select", "limit"],
                }],
            },
        )
        self.assertEqual(created.status_code, 201)
        with patch("app.main.record_governance_event") as recorded, patch("app.main.record_governance_score") as score_recorded:
            replay = self.client.post(
                f"/evaluations/{created.json()['id']}/run",
                headers=self.headers,
                json={},
            )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json()["score"], 100.0)
        self.assertEqual(replay.json()["status"], "passed")
        self.assertTrue(any(call.args[0] == "evaluation_run" for call in recorded.call_args_list))
        score_recorded.assert_called_once_with(
            score_id=replay.json()["id"],
            name="sql_generation_correctness",
            value=1.0,
            session_id=replay.json()["id"],
            comment="Automated SQL evaluation replay",
        )

    def test_evaluation_and_notebook_can_be_updated_and_deleted(self) -> None:
        evaluation = self.client.post(
            "/evaluations", headers=self.headers,
            json={"name": "Editable baseline", "cases": [{"name": "Case", "question": "Show accounts", "dialect": "postgres"}]},
        ).json()
        updated = self.client.put(
            f"/evaluations/{evaluation['id']}", headers=self.headers,
            json={"name": "Edited baseline", "description": "Updated", "cases": [{"name": "Case", "question": "Show active accounts", "dialect": "postgres", "expected_tables": ["core.accounts"]}]},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Edited baseline")
        deleted = self.client.delete(f"/evaluations/{evaluation['id']}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)

        notebook = self.client.post(
            "/notebooks", headers=self.headers,
            json={"name": "Disposable notebook", "cells": [{"id": "query", "type": "sql", "source": "SELECT 1"}]},
        ).json()
        deleted_notebook = self.client.delete(f"/notebooks/{notebook['id']}", headers=self.headers)
        self.assertEqual(deleted_notebook.status_code, 200)
        self.assertNotIn(notebook["id"], [item["id"] for item in self.client.get("/notebooks", headers=self.headers).json()])

    def test_governed_notebook_executes_sql_and_safe_python(self) -> None:
        notebook = self.client.post(
            "/notebooks",
            headers=self.headers,
            json={
                "name": "Local verification notebook",
                "cells": [
                    {"id": "intro", "type": "markdown", "source": "Verification"},
                    {"id": "query", "type": "sql", "source": "SELECT 1 AS value"},
                    {"id": "calc", "type": "python", "source": "total = sum([1, 2, 3])\ntotal"},
                ],
            },
        )
        self.assertEqual(notebook.status_code, 201)
        executed = self.client.post(f"/notebooks/{notebook.json()['id']}/run", headers=self.headers)
        self.assertEqual(executed.status_code, 201)
        self.assertEqual(executed.json()["status"], "succeeded")
        self.assertEqual(executed.json()["outputs"][2]["output"]["value"], "6")

    def test_sql_write_is_blocked(self) -> None:
        with patch("app.main.record_governance_event") as recorded:
            response = self.client.post(
                "/sql/execute",
                headers=self.headers,
                json={"sql": "DELETE FROM accounts", "dialect": "postgres"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(any(call.args[0] == "sql_guardrail" for call in recorded.call_args_list))

    def test_artifact_versions_are_durable(self) -> None:
        first = self.client.post(
            "/artifacts",
            headers=self.headers,
            json={
                "name": "Monthly deposit growth",
                "artifact_type": "sql",
                "content": "SELECT 1",
                "metadata": {"dialect": "postgres"},
            },
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            "/artifacts",
            headers=self.headers,
            json={
                "artifact_id": first.json()["id"],
                "name": "Monthly deposit growth",
                "artifact_type": "sql",
                "content": "SELECT 2",
                "metadata": {"dialect": "postgres"},
            },
        )
        self.assertEqual(second.json()["version"], 2)
        versions = self.client.get(
            f"/artifacts/{first.json()['id']}/versions", headers=self.headers
        )
        self.assertEqual([item["version"] for item in versions.json()], [2, 1])

    def test_search_and_local_model_provider(self) -> None:
        search = self.client.get("/search", headers=self.headers, params={"q": "accounts"})
        self.assertEqual(search.status_code, 200)
        self.assertGreaterEqual(len(search.json()["results"]), 1)
        providers = self.client.get("/model-providers", headers=self.headers).json()
        local_provider = next(item for item in providers if item["provider_type"] == "local_mock")
        tested = self.client.post(
            f"/model-providers/{local_provider['id']}/test", headers=self.headers
        )
        self.assertEqual(tested.status_code, 200)
        self.assertEqual(tested.json()["status"], "healthy")
        selected = self.client.post(
            f"/model-providers/{local_provider['id']}/default", headers=self.headers
        )
        self.assertEqual(selected.status_code, 200)
        self.assertTrue(selected.json()["is_default"])

    def test_local_user_lifecycle_and_password_change(self) -> None:
        email = "lifecycle.user@datapilot.local"
        temporary_password = "Temporary123!"
        replacement_password = "Replacement123!"
        created = self.client.post(
            "/admin/users",
            headers=self.headers,
            json={
                "name": "Lifecycle User",
                "email": email,
                "temporary_password": temporary_password,
                "role": "viewer",
            },
        )
        self.assertEqual(created.status_code, 201)
        user_id = created.json()["id"]

        updated = self.client.put(
            f"/admin/users/{user_id}",
            headers=self.headers,
            json={"role": "engineer", "active": False},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["role"], "engineer")
        self.assertFalse(updated.json()["active"])
        denied = self.client.post(
            "/auth/login", json={"email": email, "password": temporary_password}
        )
        self.assertEqual(denied.status_code, 401)

        reactivated = self.client.put(
            f"/admin/users/{user_id}",
            headers=self.headers,
            json={"active": True},
        )
        self.assertEqual(reactivated.status_code, 200)
        login = self.client.post(
            "/auth/login", json={"email": email, "password": temporary_password}
        )
        self.assertEqual(login.status_code, 200)
        user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        changed = self.client.post(
            "/auth/change-password",
            headers=user_headers,
            json={
                "current_password": temporary_password,
                "new_password": replacement_password,
            },
        )
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(changed.json()["must_change_password"])
        old_login = self.client.post(
            "/auth/login", json={"email": email, "password": temporary_password}
        )
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post(
            "/auth/login", json={"email": email, "password": replacement_password}
        )
        self.assertEqual(new_login.status_code, 200)

    def test_project_model_membership_and_semantic_metric_controls(self) -> None:
        original_project = next(
            item for item in self.client.get("/projects", headers=self.headers).json() if item["is_current"]
        )
        providers = self.client.get("/model-providers", headers=self.headers).json()
        local_provider = next(item for item in providers if item["provider_type"] == "local_mock")
        project = self.client.post(
            "/projects",
            headers=self.headers,
            json={"name": "Data Operations", "description": "Control-plane test", "environment": "local"},
        )
        self.assertEqual(project.status_code, 201)
        project_id = project.json()["id"]
        selected = self.client.post(f"/projects/{project_id}/select", headers=self.headers)
        self.assertTrue(selected.json()["is_current"])
        self.assertEqual(self.client.get("/datasets", headers=self.headers).json(), [])
        self.assertEqual(self.client.get("/jobs", headers=self.headers).json(), [])
        model = self.client.put(
            f"/projects/{project_id}/model-provider",
            headers=self.headers,
            json={"provider_id": local_provider["id"]},
        )
        self.assertEqual(model.status_code, 200)
        self.assertEqual(model.json()["model_provider"]["id"], local_provider["id"])
        session = self.client.get("/auth/me", headers=self.headers).json()
        self.assertEqual(session["current_project_id"], project_id)

        metric = self.client.post(
            "/semantic/metrics",
            headers=self.headers,
            json={
                "name": "Verified transaction volume",
                "description": "Acceptance metric",
                "formula": "COUNT(transaction_id)",
                "grain": "posting day",
                "owner": "Data Operations",
                "dimensions": ["channel"],
                "synonyms": ["transaction count"],
                "status": "approved",
            },
        )
        self.assertEqual(metric.status_code, 201)
        listed = self.client.get("/semantic/metrics", headers=self.headers).json()
        self.assertTrue(any(item["id"] == metric.json()["id"] for item in listed))
        removed = self.client.delete(f"/semantic/metrics/{metric.json()['id']}", headers=self.headers)
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["status"], "deleted")
        restored = self.client.post(f"/projects/{original_project['id']}/select", headers=self.headers)
        self.assertTrue(restored.json()["is_current"])

    def test_agent_tool_policy_feedback_and_job_cancel_controls(self) -> None:
        agents = self.client.get("/agents", headers=self.headers)
        tools = self.client.get("/tools", headers=self.headers)
        policy = self.client.get("/policies/effective", headers=self.headers)
        self.assertGreaterEqual(len(agents.json()), 6)
        self.assertGreaterEqual(len(tools.json()), 7)
        self.assertTrue(policy.json()["writes_require_approval"])
        detail = self.client.get(f"/agents/{agents.json()[0]['id']}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        updated_agent = self.client.put(
            f"/agents/{detail.json()['id']}",
            headers=self.headers,
            json={
                "name": detail.json()["name"],
                "purpose": detail.json()["purpose"],
                "autonomy_level": detail.json()["autonomy_level"],
                "enabled": detail.json()["enabled"],
                "policy": {**detail.json()["policy"], "acceptance_verified": True},
            },
        )
        self.assertEqual(updated_agent.status_code, 200)

        run = self.client.post(
            "/agents/runs",
            headers=self.headers,
            json={"objective": "Schedule a controlled test workflow", "autonomy_level": 2},
        )
        cancelled = self.client.post(f"/jobs/{run.json()['job_id']}/cancel", headers=self.headers)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        filtered = self.client.get("/jobs?status=CANCELLED", headers=self.headers).json()
        self.assertTrue(any(item["id"] == run.json()["job_id"] for item in filtered))
        with patch("app.main.record_governance_score") as score_recorded:
            feedback = self.client.post(
                "/feedback",
                headers=self.headers,
                json={"context_type": "agent_run", "context_id": run.json()["job_id"], "rating": "helpful", "comment": "Verified"},
            )
        self.assertEqual(feedback.status_code, 201)
        score_recorded.assert_called_once_with(
            score_id=feedback.json()["id"],
            name="user_helpfulness",
            value=True,
            data_type="BOOLEAN",
            session_id=run.json()["job_id"],
            comment="User marked output helpful",
        )

    def test_registry_versions_and_parameterized_tool_execution(self) -> None:
        agents = self.client.get("/agents", headers=self.headers).json()
        tools = self.client.get("/tools", headers=self.headers).json()
        planner = next(item for item in agents if item["name"] == "Planner")
        created = self.client.post(
            f"/agents/{planner['id']}/versions",
            headers=self.headers,
            json={
                "instructions": "Plan from catalog evidence and stop at governed approval boundaries.",
                "tool_names": ["catalog.search"],
                "input_schema": {"type": "object", "required": ["objective"]},
                "config": {"max_iterations": 3, "max_tool_calls": 6},
            },
        )
        self.assertEqual(created.status_code, 201)
        published = self.client.post(
            f"/agents/{planner['id']}/versions/{created.json()['version']}/publish",
            headers=self.headers,
        )
        self.assertEqual(published.json()["status"], "published")

        catalog_tool = next(item for item in tools if item["name"] == "catalog.search")
        updated_tool = self.client.put(
            f"/tools/{catalog_tool['id']}",
            headers=self.headers,
            json={
                "category": catalog_tool["category"],
                "description": catalog_tool["description"],
                "risk_level": catalog_tool["risk_level"],
                "enabled": catalog_tool["enabled"],
                "requires_approval": catalog_tool["requires_approval"],
            },
        )
        self.assertEqual(updated_tool.status_code, 200)
        execution = self.client.post(
            f"/tools/{catalog_tool['id']}/execute",
            headers=self.headers,
            json={"parameters": {"query": "accounts", "limit": 5}},
        )
        self.assertEqual(execution.status_code, 201)
        self.assertEqual(execution.json()["status"], "SUCCEEDED")
        self.assertGreaterEqual(execution.json()["result"]["count"], 1)
        history = self.client.get("/tools/executions", headers=self.headers).json()
        self.assertTrue(any(item["id"] == execution.json()["id"] for item in history))

    def test_pipeline_lineage_and_incident_operations(self) -> None:
        datasets = self.client.get("/datasets", headers=self.headers).json()
        source = next(item for item in datasets if item["table_name"] == "accounts")
        pipeline = self.client.post(
            "/pipelines/generate",
            headers=self.headers,
            json={
                "name": "Account operations view",
                "objective": "Publish a governed account operations view from the catalog source",
                "source_asset_ids": [source["id"]],
                "target_schema": "curated",
                "target_table": "account_operations",
            },
        )
        self.assertEqual(pipeline.status_code, 201)
        self.assertIn("CREATE OR REPLACE VIEW", pipeline.json()["generated_code"])
        self.assertEqual(
            {item["target"] for item in pipeline.json()["generated_artifacts"]},
            {"postgres_view", "dbt", "dataform"},
        )
        self.assertTrue(
            any(item["path"] == "dbt_project.yml" for item in pipeline.json()["generated_artifacts"])
        )
        customer_source = next(item for item in datasets if item["table_name"] == "customers")
        joined_pipeline = self.client.post(
            "/pipelines/generate",
            headers=self.headers,
            json={
                "name": "Customer account view",
                "objective": "Join customers to their accounts",
                "source_asset_ids": [customer_source["id"], source["id"]],
                "target_schema": "curated",
                "target_table": "customer_accounts",
            },
        )
        self.assertEqual(joined_pipeline.status_code, 201)
        self.assertIn("INNER JOIN", joined_pipeline.json()["generated_code"])
        self.assertEqual(joined_pipeline.json()["definition"]["joins"][0]["left_key"], "customer_id")
        self.assertTrue(
            any(
                item["key"] == "dataform_model"
                and "INNER JOIN" in item["content"]
                and "${ref(" in item["content"]
                for item in joined_pipeline.json()["generated_artifacts"]
            )
        )
        updated_pipeline = self.client.put(
            f"/pipelines/{joined_pipeline.json()['id']}",
            headers=self.headers,
            json={
                "name": "Customer account view v2",
                "objective": "Document the governed customer-account relationship before deployment",
            },
        )
        self.assertEqual(updated_pipeline.status_code, 200)
        self.assertEqual(updated_pipeline.json()["name"], "Customer account view v2")
        self.assertEqual(updated_pipeline.json()["current_version"], 2)
        self.assertEqual(updated_pipeline.json()["status"], "draft")
        deleted_pipeline = self.client.delete(
            f"/pipelines/{joined_pipeline.json()['id']}", headers=self.headers
        )
        self.assertEqual(deleted_pipeline.status_code, 200)
        self.assertFalse(
            any(
                item["id"] == joined_pipeline.json()["id"]
                for item in self.client.get("/pipelines", headers=self.headers).json()
            )
        )
        join_policy = self.client.post(
            "/semantic/joins",
            headers=self.headers,
            json={
                "left_asset_id": customer_source["id"],
                "right_asset_id": source["id"],
                "left_column": "customer_id",
                "right_column": "customer_id",
                "join_type": "left",
                "description": "Retain every governed customer when accounts are absent",
                "status": "approved",
            },
        )
        self.assertEqual(join_policy.status_code, 201, join_policy.json())
        policies = self.client.get("/semantic/joins", headers=self.headers)
        self.assertTrue(any(item["id"] == join_policy.json()["id"] for item in policies.json()))
        governed_pipeline = self.client.post(
            "/pipelines/generate",
            headers=self.headers,
            json={
                "name": "Governed customer account view",
                "objective": "Join customers to accounts using the approved semantic relationship",
                "source_asset_ids": [customer_source["id"], source["id"]],
                "target_schema": "curated",
                "target_table": "governed_customer_accounts",
            },
        )
        self.assertEqual(governed_pipeline.status_code, 201, governed_pipeline.json())
        self.assertIn("LEFT JOIN", governed_pipeline.json()["generated_code"])
        self.assertEqual(governed_pipeline.json()["definition"]["joins"][0]["policy_id"], join_policy.json()["id"])
        self.assertEqual(governed_pipeline.json()["definition"]["joins"][0]["source"], "semantic_policy")
        self.assertTrue(
            any(
                item["key"] == "dbt_model_properties" and "not_null" in item["content"]
                for item in governed_pipeline.json()["generated_artifacts"]
            )
        )
        postgres_only = self.client.post(
            "/pipelines/generate",
            headers=self.headers,
            json={
                "name": "Postgres only customer account view",
                "objective": "Generate only the deployable PostgreSQL artifact",
                "source_asset_ids": [customer_source["id"], source["id"]],
                "target_schema": "curated",
                "target_table": "postgres_only_customer_accounts",
                "code_targets": ["postgres_view"],
            },
        )
        self.assertEqual(postgres_only.status_code, 201, postgres_only.json())
        self.assertEqual(
            [item["target"] for item in postgres_only.json()["generated_artifacts"]],
            ["postgres_view"],
        )
        lineage = self.client.get("/lineage?relation=account_operations", headers=self.headers)
        self.assertEqual(len(lineage.json()["edges"]), 1)
        deployment = self.client.post(
            f"/pipelines/{pipeline.json()['id']}/deploy", headers=self.headers
        )
        self.assertEqual(deployment.status_code, 201)
        self.assertEqual(deployment.json()["status"], "awaiting_approval")

        run = self.client.post(
            "/agents/runs",
            headers=self.headers,
            json={"objective": "Schedule incident fixture", "autonomy_level": 2},
        ).json()
        self.client.post(f"/jobs/{run['job_id']}/cancel", headers=self.headers)
        diagnosis = self.client.post(f"/jobs/{run['job_id']}/diagnose", headers=self.headers)
        self.assertEqual(diagnosis.status_code, 201)
        retry = self.client.post(f"/jobs/{run['job_id']}/retry", headers=self.headers)
        self.assertEqual(retry.status_code, 201)
        incidents = self.client.get("/incidents", headers=self.headers).json()
        self.assertTrue(any(item["job_id"] == run["job_id"] for item in incidents))

    def test_pipeline_package_export_and_validation(self) -> None:
        datasets = self.client.get("/datasets", headers=self.headers).json()
        source = next(item for item in datasets if item["table_name"] == "customers")
        pipeline = self.client.post(
            "/pipelines/generate",
            headers=self.headers,
            json={
                "name": "Customer export package",
                "objective": "Prepare reusable generated packages for integration",
                "source_asset_ids": [source["id"]],
                "target_schema": "curated",
                "target_table": "customer_export_package",
            },
        )
        self.assertEqual(pipeline.status_code, 201, pipeline.json())
        pipeline_id = pipeline.json()["id"]

        dbt_package = self.client.get(
            f"/pipelines/{pipeline_id}/packages/dbt",
            headers=self.headers,
        )
        self.assertEqual(dbt_package.status_code, 200, dbt_package.json())
        self.assertEqual(dbt_package.json()["target"], "dbt")
        self.assertTrue(any(item["path"] == "dbt_project.yml" for item in dbt_package.json()["files"]))
        self.assertTrue(any(item["path"] == "profiles.example.yml" for item in dbt_package.json()["files"]))
        self.assertEqual(dbt_package.json()["delivery_config"]["delivery_mode"], "download_only")
        self.assertTrue(
            any(item["step"] == "Manual repository handoff" for item in dbt_package.json()["delivery_plan"])
        )

        default_delivery = self.client.get(
            f"/pipelines/{pipeline_id}/packages/dbt/delivery-config",
            headers=self.headers,
        )
        self.assertEqual(default_delivery.status_code, 200, default_delivery.json())
        self.assertEqual(default_delivery.json()["delivery_config"]["base_branch"], "main")

        invalid_delivery = self.client.put(
            f"/pipelines/{pipeline_id}/packages/dbt/delivery-config",
            headers=self.headers,
            json={
                "delivery_mode": "git_prepare",
                "git_repository": "https://example.com/org/analytics.git",
                "create_branch": False,
                "create_pr": True,
            },
        )
        self.assertEqual(invalid_delivery.status_code, 422)

        saved_delivery = self.client.put(
            f"/pipelines/{pipeline_id}/packages/dbt/delivery-config",
            headers=self.headers,
            json={
                "delivery_mode": "git_prepare",
                "git_repository": "https://example.com/org/analytics.git",
                "git_provider": "github",
                "base_branch": "main",
                "export_subdirectory": "generated/pipelines/customer_export_package",
                "create_branch": True,
                "branch_strategy": "custom",
                "branch_name_template": "datapilot/dbt/{pipeline_slug}/v{pipeline_version}",
                "create_pr": True,
                "pr_title_template": "Export {pipeline_name} dbt package",
                "pr_body_template": "Generated package for review only.",
            },
        )
        self.assertEqual(saved_delivery.status_code, 200, saved_delivery.json())
        self.assertEqual(saved_delivery.json()["delivery_config"]["delivery_mode"], "git_prepare")
        self.assertTrue(saved_delivery.json()["delivery_config"]["create_pr"])
        self.assertTrue(
            any(item["step"] == "Prepare PR metadata" for item in saved_delivery.json()["delivery_plan"])
        )

        archive = self.client.get(
            f"/pipelines/{pipeline_id}/packages/dbt/archive",
            headers=self.headers,
        )
        self.assertEqual(archive.status_code, 200)
        self.assertEqual(archive.headers["content-type"], "application/zip")
        zipped = zipfile.ZipFile(io.BytesIO(archive.content))
        names = set(zipped.namelist())
        root_dir = dbt_package.json()["root_dir"]
        self.assertIn(f"{root_dir}/dbt_project.yml", names)
        self.assertIn(f"{root_dir}/profiles.example.yml", names)
        self.assertIn(f"{root_dir}/README.md", names)
        self.assertIn(f"{root_dir}/.datapilot/package_manifest.json", names)
        manifest = json.loads(zipped.read(f"{root_dir}/.datapilot/package_manifest.json").decode("utf-8"))
        self.assertEqual(manifest["delivery_config"]["git_repository"], "https://example.com/org/analytics.git")
        self.assertTrue(manifest["delivery_config"]["create_branch"])

        # Test the no-CLI outcome independently of an optional managed CLI
        # installed under .tools on a developer machine.
        with patch("app.pipeline_codegen.validators._resolve_cli_path", return_value=None):
            validation = self.client.post(
                f"/pipelines/{pipeline_id}/packages/dbt/validate",
                headers=self.headers,
            )
        self.assertEqual(validation.status_code, 200, validation.json())
        self.assertEqual(validation.json()["status"], "partial")
        self.assertTrue(
            any(
                item["name"] == "cli_validation"
                and item["status"] == "partial"
                and "not installed" in item["detail"]
                for item in validation.json()["checks"]
            )
        )

        dataform_package = self.client.get(
            f"/pipelines/{pipeline_id}/packages/dataform",
            headers=self.headers,
        )
        self.assertEqual(dataform_package.status_code, 200, dataform_package.json())
        self.assertTrue(any(item["path"] == "workflow_settings.yaml" for item in dataform_package.json()["files"]))
        self.assertTrue(any(item["path"] == "definitions/_package_assertions.sqlx" for item in dataform_package.json()["files"]))

        with patch("app.pipeline_codegen.validators._resolve_cli_path", return_value="dbt"), patch(
            "app.pipeline_codegen.validators.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="parse ok", stderr=""),
        ):
            validated = self.client.post(
                f"/pipelines/{pipeline_id}/packages/dbt/validate",
                headers=self.headers,
            )
        self.assertEqual(validated.status_code, 200, validated.json())
        self.assertEqual(validated.json()["status"], "passed")
        self.assertEqual(validated.json()["command"][1], "parse")
        self.assertTrue(
            any(item["name"] == "cli_validation" and item["status"] == "passed" for item in validated.json()["checks"])
        )

    def test_sql_generation_reuses_cached_result_for_equivalent_request(self) -> None:
        first = self.client.post(
            "/sql/generate",
            headers=self.headers,
            json={"question": "Show monthly account growth", "dialect": "postgres"},
        )
        self.assertEqual(first.status_code, 200, first.json())
        self.assertFalse(first.json()["cache"]["hit"])

        second = self.client.post(
            "/sql/generate",
            headers=self.headers,
            json={"question": "Show monthly account growth", "dialect": "postgres"},
        )
        self.assertEqual(second.status_code, 200, second.json())
        self.assertTrue(second.json()["cache"]["hit"])
        self.assertEqual(second.json()["provider"]["mode"], "cache_reuse")
        self.assertEqual(first.json()["sql"], second.json()["sql"])

    def test_local_agent_fallback_persists_trace_outputs(self) -> None:
        run = self.client.post(
            "/agents/runs",
            headers=self.headers,
            json={"objective": "Summarize available customer data", "autonomy_level": 2},
        )
        self.assertEqual(run.status_code, 201, run.json())
        self.assertEqual(run.json()["status"], "SUCCEEDED")

        job = self.client.get(f"/jobs/{run.json()['job_id']}", headers=self.headers)
        self.assertEqual(job.status_code, 200, job.json())
        self.assertGreaterEqual(len(job.json()["outputs"]), 2)
        self.assertTrue(any(item["type"] == "grounding" for item in job.json()["outputs"]))
        self.assertTrue(any(item["type"] == "plan" for item in job.json()["outputs"]))

    def test_agent_evaluation_replays_safe_runs_and_simulates_approval(self) -> None:
        evaluation = self.client.post(
            "/evaluations",
            headers=self.headers,
            json={
                "name": "Agent policy baseline",
                "description": "Verify bounded execution and approval boundaries.",
                "cases": [
                    {
                        "name": "Read-only catalog review",
                        "question": "Summarize available customer data",
                        "case_type": "agent_run",
                        "expected_agents": ["Planner", "Metadata", "Policy"],
                        "expected_tools": ["catalog.search"],
                        "expects_approval": False,
                    },
                    {
                        "name": "Publish boundary",
                        "question": "Publish a curated customer dataset",
                        "case_type": "agent_run",
                        "expected_agents": ["Policy"],
                        "expects_approval": True,
                    },
                ],
            },
        )
        self.assertEqual(evaluation.status_code, 201, evaluation.json())

        replay = self.client.post(
            f"/evaluations/{evaluation.json()['id']}/run", headers=self.headers, json={}
        )
        self.assertEqual(replay.status_code, 201, replay.json())
        self.assertEqual(replay.json()["status"], "passed")
        safe_case, approval_case = replay.json()["results"]
        self.assertEqual(safe_case["case_type"], "agent_run")
        self.assertFalse(safe_case["simulation"])
        self.assertIn("catalog.search", safe_case["observed_tools"])
        self.assertTrue(approval_case["simulation"])
        self.assertEqual(approval_case["job_status"], "SIMULATED_APPROVAL_REQUIRED")

    def test_feedback_creates_human_review_suggestion_only(self) -> None:
        feedback = self.client.post(
            "/feedback",
            headers=self.headers,
            json={
                "context_type": "sql",
                "context_id": "artifact-123",
                "rating": "not_helpful",
                "comment": "The query needs a clearer customer status definition.",
            },
        )
        self.assertEqual(feedback.status_code, 201, feedback.json())
        suggestion_id = feedback.json()["learning_suggestion_id"]
        self.assertIsNotNone(suggestion_id)

        suggestions = self.client.get("/learning-suggestions?status=open", headers=self.headers)
        self.assertEqual(suggestions.status_code, 200, suggestions.json())
        suggestion = next(item for item in suggestions.json() if item["id"] == suggestion_id)
        self.assertEqual(suggestion["category"], "sql_grounding")
        self.assertEqual(suggestion["status"], "open")
        self.assertIn("do not change runtime behavior automatically", suggestion["proposed_change"]["action"])

        reviewed = self.client.put(
            f"/learning-suggestions/{suggestion_id}",
            headers=self.headers,
            json={"status": "accepted", "note": "Create a versioned semantic definition after review."},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.json())
        self.assertEqual(reviewed.json()["status"], "accepted")
        self.assertEqual(reviewed.json()["review_note"], "Create a versioned semantic definition after review.")

    def test_agent_golden_trace_scorecard_and_red_team_suite(self) -> None:
        evaluation = self.client.post(
            "/evaluations",
            headers=self.headers,
            json={
                "name": "Golden agent trace",
                "cases": [
                    {
                        "name": "Catalog trace",
                        "question": "Summarize available customer data",
                        "case_type": "agent_run",
                        "expected_agents": ["Planner", "Metadata", "Policy"],
                        "expected_tools": ["catalog.search"],
                        "expects_approval": False,
                    }
                ],
            },
        )
        self.assertEqual(evaluation.status_code, 201, evaluation.json())
        first_run = self.client.post(
            f"/evaluations/{evaluation.json()['id']}/run", headers=self.headers, json={}
        )
        self.assertEqual(first_run.status_code, 201, first_run.json())
        promoted = self.client.post(
            f"/evaluations/{evaluation.json()['id']}/baseline",
            headers=self.headers,
            json={"run_id": first_run.json()["id"]},
        )
        self.assertEqual(promoted.status_code, 200, promoted.json())
        self.assertEqual(promoted.json()["promoted_cases"], ["Catalog trace"])
        replay = self.client.post(
            f"/evaluations/{evaluation.json()['id']}/run", headers=self.headers, json={}
        )
        self.assertEqual(replay.status_code, 201, replay.json())
        self.assertTrue(any(check["kind"] == "golden_agents" and check["passed"] for check in replay.json()["results"][0]["checks"]))
        planner = next(item for item in self.client.get("/agents", headers=self.headers).json() if item["name"] == "Planner")
        scorecard = self.client.get(f"/agents/{planner['id']}/scorecard", headers=self.headers)
        self.assertEqual(scorecard.status_code, 200, scorecard.json())
        self.assertGreaterEqual(scorecard.json()["evaluated_cases"], 2)
        self.assertEqual(scorecard.json()["golden_failures"], 0)

        red_team = self.client.post("/evaluations/red-team", headers=self.headers, json={})
        self.assertEqual(red_team.status_code, 201, red_team.json())
        red_team_run = self.client.post(
            f"/evaluations/{red_team.json()['id']}/run", headers=self.headers, json={}
        )
        self.assertEqual(red_team_run.status_code, 201, red_team_run.json())
        self.assertEqual(red_team_run.json()["status"], "passed")
        self.assertTrue(all(result["simulation"] for result in red_team_run.json()["results"][:4]))

    def test_relation_aware_query_tool_wizard_and_external_extraction(self) -> None:
        datasets = self.client.get("/datasets", headers=self.headers).json()
        accounts = next(item for item in datasets if item["table_name"] == "accounts")
        relation_options = self.client.get("/query-tools/relation-options", headers=self.headers)
        self.assertEqual(relation_options.status_code, 200, relation_options.json())
        self.assertTrue(any(option["asset_id"] == accounts["id"] for option in relation_options.json()))
        preview = self.client.post(
            "/query-tools/wizard/preview",
            headers=self.headers,
            json={"asset_id": accounts["id"], "template": "filtered_count", "filter_column": "status"},
        )
        self.assertEqual(preview.status_code, 200, preview.json())
        suggested = preview.json()["suggested_tool"]
        self.assertEqual(suggested["allowed_relations"], ["core.accounts"])
        created_tool = self.client.post("/query-tools", headers=self.headers, json=suggested)
        self.assertEqual(created_tool.status_code, 201, created_tool.json())

        extraction = self.client.post(
            "/external-extractions",
            headers=self.headers,
            json={
                "name": "Accounts source replica",
                "connector_id": accounts["connector_id"],
                "source_asset_id": accounts["id"],
                "target_table": "accounts_source_replica",
                "load_mode": "replace",
                "watermark_column": "opened_at",
                "batch_limit": 100,
            },
        )
        self.assertEqual(extraction.status_code, 201, extraction.json())
        with patch(
            "app.main.execute_connector_query",
            return_value={
                "columns": ["account_id", "customer_id", "account_type", "status", "opened_at"],
                "rows": [
                    {"account_id": 901, "customer_id": 51, "account_type": "checking", "status": "active", "opened_at": "2026-01-01T00:00:00Z"},
                    {"account_id": 902, "customer_id": 52, "account_type": "savings", "status": "closed", "opened_at": "2026-01-02T00:00:00Z"},
                ],
                "row_count": 2,
                "truncated": False,
                "limit": 100,
                "duration_ms": 1,
            },
        ):
            executed = self.client.post(
                f"/external-extractions/{extraction.json()['id']}/run", headers=self.headers
            )
        self.assertEqual(executed.status_code, 201, executed.json())
        self.assertEqual(executed.json()["loaded_rows"], 2)
        self.assertEqual(executed.json()["last_watermark"], "2026-01-02T00:00:00Z")
        lineage = self.client.get("/lineage?relation=accounts_source_replica", headers=self.headers)
        self.assertTrue(any(edge["source_relation"] == "core.accounts" for edge in lineage.json()["edges"]))

    def test_z_external_gateway_conversations_prompts_and_retention(self) -> None:
        tool = self.client.post(
            "/query-tools",
            headers=self.headers,
            json={
                "name": "accounts.count_since",
                "description": "Count accounts at or above a supplied identifier.",
                "purpose": "Support account-volume analysis with a bounded identifier filter.",
                "data_source": "Local PostgreSQL staging",
                "line_of_business": "Retail Banking",
                "owner": "Account Operations",
                "tags": ["accounts", "volume"],
                "sql_template": "SELECT COUNT(*) AS total FROM accounts WHERE account_id >= :minimum_id",
                "parameter_schema": {
                    "type": "object",
                    "required": ["minimum_id"],
                    "properties": {"minimum_id": {"type": "integer"}},
                    "additionalProperties": False,
                },
                "allowed_relations": ["accounts"],
                "row_limit": 10,
                "timeout_seconds": 10,
            },
        )
        self.assertEqual(tool.status_code, 201)
        tool_id = tool.json()["id"]
        self.assertEqual(
            self.client.post(f"/query-tools/{tool_id}/publish", headers=self.headers).json()["status"],
            "published",
        )
        client = self.client.post(
            "/external-clients",
            headers=self.headers,
            json={"name": "Acceptance agent", "scopes": ["tools:list", "tools:invoke"]},
        )
        self.assertEqual(client.status_code, 201)
        token = client.json()["token"]
        grant = self.client.post(
            f"/query-tools/{tool_id}/grants",
            headers=self.headers,
            json={"external_client_id": client.json()["id"], "enabled": True},
        )
        self.assertEqual(grant.status_code, 201)
        external_headers = {"Authorization": f"Bearer {token}"}
        registry = self.client.get(
            "/external/v1/query-tools",
            headers=external_headers,
            params={"q": "volume", "line_of_business": "retail"},
        )
        self.assertEqual(registry.status_code, 200)
        self.assertEqual(registry.json()["count"], 1)
        self.assertEqual(registry.json()["tools"][0]["owner"], "Account Operations")
        self.assertEqual(registry.json()["tools"][0]["tags"], ["accounts", "volume"])
        detail = self.client.get(
            "/external/v1/query-tools/accounts.count_since", headers=external_headers
        )
        self.assertEqual(detail.json()["data_source"], "Local PostgreSQL staging")
        invocation = self.client.post(
            "/external/v1/query-tools/accounts.count_since/invoke",
            headers=external_headers,
            json={"parameters": {"minimum_id": 50150}},
        )
        self.assertEqual(invocation.status_code, 200)
        self.assertEqual(invocation.json()["rows"][0]["total"], 4)
        analytics = self.client.get(f"/query-tools/{tool_id}/analytics", headers=self.headers)
        self.assertEqual(analytics.status_code, 200, analytics.json())
        self.assertEqual(analytics.json()["invocation_count"], 1)
        self.assertEqual(analytics.json()["success_rate"], 100.0)
        self.assertEqual(analytics.json()["rows_returned"], 1)
        self.assertEqual(analytics.json()["parameter_key_usage"], [{"parameter": "minimum_id", "invocations": 1}])
        registry_summary = self.client.get("/query-tools/summary", headers=self.headers)
        self.assertEqual(registry_summary.status_code, 200, registry_summary.json())
        self.assertEqual(registry_summary.json()["published"], 1)
        summary_tool = next(item for item in registry_summary.json()["tools"] if item["id"] == tool_id)
        self.assertEqual(summary_tool["invocation_count"], 1)
        mcp = self.client.post(
            "/mcp",
            headers=external_headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        self.assertEqual(mcp.json()["result"]["tools"][0]["name"], "accounts.count_since")
        self.assertEqual(
            mcp.json()["result"]["tools"][0]["_meta"]["com.datapilot.registry"]["line_of_business"],
            "Retail Banking",
        )

        connector = self.client.post(
            "/connectors",
            headers=self.headers,
            json={
                "name": "customer_db",
                "connector_type": "oracle",
                "host": "oracle.internal",
                "database": "CUSTOMER",
                "read_only": True,
            },
        )
        self.assertEqual(connector.status_code, 201)
        source_driven_sql = self.client.post(
            "/sql/generate",
            headers=self.headers,
            json={"question": "Show customer accounts", "dialect": "postgres", "connector_id": connector.json()["id"]},
        )
        self.assertEqual(source_driven_sql.status_code, 200)
        self.assertEqual(source_driven_sql.json()["dialect"], "oracle")
        self.assertEqual(source_driven_sql.json()["source"]["name"], "customer_db")

        conversation = self.client.post(
            "/conversations", headers=self.headers, json={"title": "Account analysis"}
        ).json()
        answer = self.client.post(
            f"/conversations/{conversation['id']}/messages",
            headers=self.headers,
            json={"content": "Show monthly account growth", "dialect": "postgres"},
        )
        self.assertEqual(answer.status_code, 201)
        self.assertIn("sql", answer.json()["structured"])
        self.assertTrue(answer.json()["structured"]["memory"]["persisted"])
        follow_up = self.client.post(
            f"/conversations/{conversation['id']}/messages",
            headers=self.headers,
            json={"content": "Now narrow that result to active accounts", "dialect": "postgres"},
        )
        self.assertEqual(follow_up.status_code, 201)
        self.assertGreaterEqual(follow_up.json()["structured"]["memory"]["prior_messages_used"], 2)
        self.assertEqual(follow_up.json()["structured"]["source"]["connector_type"], "local_files")
        listed_conversations = self.client.get("/conversations", headers=self.headers).json()
        self.assertEqual(listed_conversations[0]["id"], conversation["id"])
        report = self.client.post(
            f"/conversations/{conversation['id']}/report",
            headers=self.headers,
            json={"name": "Account growth report"},
        )
        self.assertEqual(report.json()["artifact_type"], "report")

        prompt = self.client.post(
            "/prompts",
            headers=self.headers,
            json={"name": "SQL analyst prompt", "system_prompt": "Return governed SQL.", "template": "Question: {{question}}", "variables": ["question"], "metadata": {}},
        )
        self.assertEqual(prompt.status_code, 201)
        rollback = self.client.post(
            f"/prompts/{prompt.json()['id']}/rollback",
            headers=self.headers,
            json={"version": 1},
        )
        self.assertEqual(rollback.json()["version"], 2)
        retention = self.client.post(
            "/retention-policies",
            headers=self.headers,
            json={"resource_type": "external_invocations", "retention_days": 365, "enabled": True},
        )
        self.assertEqual(retention.status_code, 201)


if __name__ == "__main__":
    unittest.main()
