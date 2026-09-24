"""Server-side pagination (X-Total-Count / X-Has-More), grouping facets and the
external invocation history (filters, detail, 24h/7d summary)."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-pagination-{uuid4().hex}.db"
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

from app import rate_limit
from app.database import SessionLocal, engine
from app.main import app
from app.models import Job, User
from app.routers.query_tools import _redacted_parameters


class PaginationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        login = cls.client.post("/auth/login", json={"email": "admin@datapilot.local", "password": "ChangeMe123!"}).json()
        cls.headers = {"Authorization": f"Bearer {login['access_token']}"}
        cls.project_id = login["user"]["current_project_id"]
        with SessionLocal() as db:
            admin_id = db.scalar(select(User.id).where(User.email == "admin@datapilot.local"))
            for index in range(7):
                db.add(Job(
                    project_id=cls.project_id, title=f"Paging probe {index}", job_type="paging_probe" if index < 5 else "paging_other",
                    status="SUCCEEDED" if index % 2 else "FAILED", progress=100, plan=[], evidence=[], logs=[], outputs=[], created_by=admin_id,
                ))
            db.commit()
        rate_limit.reset_client_cache()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        rate_limit.reset_client_cache()
        engine.dispose()
        if database_file.exists():
            try:
                database_file.unlink()
            except OSError:
                pass

    def setUp(self) -> None:
        self.redis_env = mock.patch.dict(os.environ, {"REDIS_URL": ""})
        self.redis_env.start()
        rate_limit.reset_client_cache()

    def tearDown(self) -> None:
        self.redis_env.stop()
        rate_limit.reset_client_cache()

    def _get(self, path: str, **params):
        response = self.client.get(path, headers=self.headers, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    # --- generic pagination contract ----------------------------------------------

    def test_pages_carry_total_and_has_more_headers(self) -> None:
        first = self._get("/jobs", q="paging probe", limit=3)
        self.assertEqual(len(first.json()), 3)
        self.assertEqual(first.headers["X-Total-Count"], "7")
        self.assertEqual(first.headers["X-Has-More"], "true")
        last = self._get("/jobs", q="paging probe", limit=3, offset=6)
        self.assertEqual(len(last.json()), 1)
        self.assertEqual(last.headers["X-Has-More"], "false")
        seen = {item["id"] for offset in (0, 3, 6) for item in self._get("/jobs", q="paging probe", limit=3, offset=offset).json()}
        self.assertEqual(len(seen), 7, "pages must not overlap")

    def test_without_limit_the_legacy_full_list_is_returned(self) -> None:
        response = self._get("/jobs")
        self.assertEqual(response.headers["X-Total-Count"], str(len(response.json())))
        self.assertEqual(response.headers["X-Has-More"], "false")
        self.assertGreaterEqual(len(response.json()), 7)

    def test_limit_is_bounded(self) -> None:
        self.assertEqual(self.client.get("/jobs", headers=self.headers, params={"limit": 201}).status_code, 422)
        self.assertEqual(self.client.get("/jobs", headers=self.headers, params={"limit": 0}).status_code, 422)
        self.assertEqual(self.client.get("/jobs", headers=self.headers, params={"offset": -1}).status_code, 422)

    def test_job_filters_and_type_facets(self) -> None:
        probes = self._get("/jobs", job_type="paging_probe", limit=50)
        self.assertEqual(probes.headers["X-Total-Count"], "5")
        self.assertTrue(all(item["job_type"] == "paging_probe" for item in probes.json()))
        failed = self._get("/jobs", q="paging probe", status="FAILED", limit=50)
        self.assertEqual(failed.headers["X-Total-Count"], "4")
        facets = self._get("/jobs/facets", q="paging probe").json()
        self.assertEqual(facets["total"], 7)
        self.assertEqual({item["value"]: item["count"] for item in facets["job_type"]}, {"paging_probe": 5, "paging_other": 2})
        self.assertEqual(facets["job_type"][0]["value"], "paging_probe", "largest group first")

    def test_dataset_pages_filters_and_facets_agree(self) -> None:
        everything = self._get("/datasets").json()
        self.assertTrue(everything, "demo catalog expected")
        page = self._get("/datasets", limit=2)
        self.assertEqual(page.headers["X-Total-Count"], str(len(everything)))
        self.assertEqual([item["id"] for item in page.json()], [item["id"] for item in everything[:2]])
        facets = self._get("/datasets/facets").json()
        self.assertEqual(facets["total"], len(everything))
        for key in ("source", "category", "schema"):
            self.assertEqual(sum(item["count"] for item in facets[key]), len(everything))
        source = facets["source"][0]
        by_source = self._get("/datasets", source=source["value"], limit=200)
        self.assertEqual(by_source.headers["X-Total-Count"], str(source["count"]))
        one = self._get("/datasets", id=everything[0]["id"]).json()
        self.assertEqual([item["id"] for item in one], [everything[0]["id"]])

    def test_other_list_endpoints_send_pagination_headers(self) -> None:
        for path in ("/approvals", "/artifacts", "/pipelines", "/quality/rules", "/query-tools", "/files", "/audit", "/verified-queries", "/router/decisions", "/sql/history", "/incidents", "/admin/users"):
            with self.subTest(path):
                response = self._get(path, limit=1)
                self.assertIn("X-Total-Count", response.headers)
                self.assertLessEqual(len(response.json()), 1)
                self.assertEqual(response.headers["X-Has-More"], "true" if int(response.headers["X-Total-Count"]) > 1 else "false")
        decided = self._get("/approvals", status="decided", limit=200).json()
        self.assertTrue(all(item["status"] != "pending" for item in decided))
        for path, list_path in (("/quality/rules/facets", "/quality/rules"), ("/verified-queries/facets", "/verified-queries")):
            with self.subTest(path):
                facets = self._get(path).json()
                self.assertEqual(str(facets["total"]), self._get(list_path, limit=1).headers["X-Total-Count"])
        for backend in ("local", "jev"):
            rows = self._get("/router/decisions", backend=backend, limit=200).json()
            self.assertTrue(all(row["backend"] == backend or row["backend"].startswith(f"{backend}:") for row in rows))

    # --- external invocation history -------------------------------------------

    def _tool(self, sql: str, relations: list[str]) -> dict:
        tool = self.client.post("/query-tools", headers=self.headers, json={
            "name": f"history.probe_{uuid4().hex[:8]}", "description": "History probe.", "purpose": "Invocation history test.",
            "data_source": "History source", "line_of_business": "Platform", "owner": "Platform", "tags": ["diagnostic"],
            "sql_template": sql, "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "allowed_relations": relations, "row_limit": 5, "timeout_seconds": 5,
        })
        self.assertEqual(tool.status_code, 201, tool.text)
        self.assertEqual(self.client.post(f"/query-tools/{tool.json()['id']}/publish", headers=self.headers).status_code, 200)
        return tool.json()

    def test_invocation_history_records_channel_and_filters(self) -> None:
        ok_tool = self._tool("SELECT 1 AS ok", [])
        broken_tool = self._tool("SELECT * FROM history_missing_relation", ["history_missing_relation"])
        created = self.client.post("/external-clients", headers=self.headers, json={"name": f"History agent {uuid4().hex[:6]}", "scopes": ["tools:list", "tools:invoke"]}).json()
        for tool in (ok_tool, broken_tool):
            self.assertEqual(self.client.post(f"/query-tools/{tool['id']}/grants", headers=self.headers, json={"external_client_id": created["id"], "enabled": True}).status_code, 201)
        external = {"Authorization": f"Bearer {created['token']}"}
        self.assertEqual(self.client.post(f"/external/v1/query-tools/{ok_tool['name']}/invoke", headers=external, json={"parameters": {}}).status_code, 200)
        self.assertEqual(self.client.post(f"/external/v1/query-tools/{broken_tool['name']}/invoke", headers=external, json={"parameters": {}}).status_code, 422)
        mcp = self.client.post("/mcp", headers=external, json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": ok_tool["name"], "arguments": {}}})
        self.assertFalse(mcp.json()["result"]["isError"])

        history = self._get("/external-invocations", client_id=created["id"], limit=2)
        self.assertEqual(history.headers["X-Total-Count"], "3")
        self.assertEqual(history.headers["X-Has-More"], "true")
        newest = history.json()[0]
        self.assertEqual((newest["channel"], newest["tool_name"], newest["client_name"], newest["client_id"]), ("mcp", ok_tool["name"], created["name"], created["client_id"]))
        self.assertEqual(newest["row_count"], 1)

        by_channel = self._get("/external-invocations", client_id=created["id"], channel="rest", limit=50).json()
        self.assertEqual(len(by_channel), 2)
        failed = self._get("/external-invocations", client_id=created["id"], status="failed", limit=50).json()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["tool_name"], broken_tool["name"])
        self.assertTrue(failed[0]["error"])
        by_tool = self._get("/external-invocations", client_id=created["id"], tool=ok_tool["name"], limit=50).json()
        self.assertEqual({item["query_tool_id"] for item in by_tool}, {ok_tool["id"]})
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.assertEqual(self._get("/external-invocations", client_id=created["id"], since=future).json(), [])
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertEqual(len(self._get("/external-invocations", client_id=created["id"], since=past, until=future).json()), 3)

        detail = self._get(f"/external-invocations/{failed[0]['id']}").json()
        self.assertEqual(detail["tool"]["name"], broken_tool["name"])
        self.assertEqual(detail["tool"]["data_source"], "History source")
        self.assertEqual(detail["client"]["client_id"], created["client_id"])
        self.assertEqual(self.client.get("/external-invocations/does-not-exist", headers=self.headers).status_code, 404)

        summary = self._get("/external-invocations/summary").json()
        day = summary["windows"]["24h"]
        self.assertGreaterEqual(day["total"], 3)
        self.assertEqual(day["total"], day["succeeded"] + day["failed"])
        client_bucket = next(item for item in day["by_client"] if item["id"] == created["id"])
        self.assertEqual((client_bucket["count"], client_bucket["failed"], client_bucket["name"]), (3, 1, created["name"]))
        self.assertIn("mcp", {item["id"] for item in day["by_channel"]})
        self.assertGreaterEqual(summary["windows"]["7d"]["total"], day["total"])

    def test_invocation_parameters_are_redacted_for_display(self) -> None:
        shown = _redacted_parameters({"account_id": 7, "passenger_id": 3, "api_token": "abc", "nested": {"password": "x", "note": "y" * 500}, "ids": list(range(30))})
        self.assertEqual((shown["account_id"], shown["passenger_id"]), (7, 3))
        self.assertEqual(shown["api_token"], "***")
        self.assertEqual(shown["nested"]["password"], "***")
        self.assertEqual(len(shown["nested"]["note"]), 201)
        self.assertEqual(len(shown["ids"]), 21)

    def test_query_tool_registry_pages_and_groups(self) -> None:
        self._tool("SELECT 2 AS ok", [])
        facets = self._get("/query-tools/facets").json()
        self.assertEqual(sum(item["count"] for item in facets["data_source"]), facets["total"])
        source = next(item for item in facets["data_source"] if item["value"] == "History source")
        grouped = self._get("/query-tools", data_source="History source", limit=200)
        self.assertEqual(grouped.headers["X-Total-Count"], str(source["count"]))
        self.assertTrue(all(item["data_source"] == "History source" for item in grouped.json()))


if __name__ == "__main__":
    unittest.main()
