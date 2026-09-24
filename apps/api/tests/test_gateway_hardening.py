"""Tool-runtime and external-gateway hardening (docs/AGENTS_TOOLS_AND_JEV.md section 5, items 3, 6, 9-13)."""
import os
import socket
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from uuid import uuid4

database_file = Path(tempfile.gettempdir()) / f"datapilot-test-gateway-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("QDRANT_URL", "")
os.environ.setdefault("SUPERSET_INTERNAL_URL", "")
os.environ.setdefault("SUPERSET_ADMIN_PASSWORD", "")
os.environ.setdefault("SUPERSET_EDITOR_SSO_SECRET", "test-editor-secret")
os.environ.setdefault("ENABLE_DEMO_DATA", "true")
os.environ["DECISION_ROUTER_BACKEND"] = "local"

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import rate_limit, tool_runtime
from app.catalog_scope import queryable_asset_ids, reset_cache
from app.database import SessionLocal, engine
from app.main import app
from app.models import DataAsset, ExternalClient, Project
from app.tool_runtime import ToolRuntimeError, ToolTimeoutError, execute_tool

OPEN_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": True}
SQL_SCHEMA = {"type": "object", "required": ["sql"], "properties": {"sql": {"type": "string"}, "limit": {"type": "integer"}}}


def _addrinfo(*addresses: str):
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in addresses]
    return fake


def _run_builtin(handler_name: str, parameters: dict, project_id: str, timeout_seconds: int = 5, schema: dict | None = None):
    with SessionLocal() as db:
        return execute_tool(db, "builtin", handler_name, None, "POST", schema or OPEN_SCHEMA, parameters, project_id, timeout_seconds, 0, 0)


class RateLimitFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        rate_limit.reset_client_cache()
        rate_limit.reset_local_windows()

    def tearDown(self) -> None:
        rate_limit.reset_client_cache()
        rate_limit.reset_local_windows()

    def test_without_redis_the_limit_is_enforced_in_process(self) -> None:
        with mock.patch.dict(os.environ, {"REDIS_URL": ""}):
            key = f"probe:{uuid4().hex}"
            results = [rate_limit.check_rate_limit(key, 3, 60) for _ in range(4)]
        self.assertEqual([item.allowed for item in results], [True, True, True, False])
        self.assertGreaterEqual(results[-1].retry_after_seconds, 1)

    def test_sliding_window_releases_capacity_as_hits_age_out(self) -> None:
        clock = [1000.0]
        with mock.patch.dict(os.environ, {"REDIS_URL": ""}), mock.patch("app.rate_limit.time.monotonic", side_effect=lambda: clock[0]):
            key = f"slide:{uuid4().hex}"
            self.assertTrue(rate_limit.check_rate_limit(key, 2, 60).allowed)
            clock[0] += 30
            self.assertTrue(rate_limit.check_rate_limit(key, 2, 60).allowed)
            self.assertFalse(rate_limit.check_rate_limit(key, 2, 60).allowed)
            clock[0] += 31  # first hit is now older than the window
            self.assertTrue(rate_limit.check_rate_limit(key, 2, 60).allowed)
            self.assertFalse(rate_limit.check_rate_limit(key, 2, 60).allowed)

    def test_redis_errors_fall_back_instead_of_failing_open(self) -> None:
        class BrokenRedis:
            def incr(self, _key):
                raise ConnectionError("redis down")

        rate_limit.configure_client(BrokenRedis())
        key = f"broken:{uuid4().hex}"
        self.assertTrue(rate_limit.check_rate_limit(key, 1, 60).allowed)
        self.assertFalse(rate_limit.check_rate_limit(key, 1, 60).allowed)


class HttpToolEgressTests(unittest.TestCase):
    def _mock_client(self, handler):
        return lambda timeout: httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    def test_private_addresses_are_refused_even_when_allowlisted(self) -> None:
        sent = []
        with mock.patch.dict(os.environ, {"TOOL_HTTP_ALLOWLIST": "api.example.com", "TOOL_HTTP_ALLOW_PRIVATE": ""}), \
                mock.patch("app.tool_runtime.socket.getaddrinfo", side_effect=_addrinfo("10.1.2.3")), \
                mock.patch("app.tool_runtime._http_client", self._mock_client(lambda request: sent.append(request) or httpx.Response(200, json={}))):
            for address in ("10.1.2.3", "127.0.0.1", "169.254.169.254", "::1", "::ffff:192.168.0.1", "224.0.0.1"):
                with mock.patch("app.tool_runtime.socket.getaddrinfo", side_effect=_addrinfo(address)):
                    with self.assertRaisesRegex(ToolRuntimeError, "private or reserved"):
                        tool_runtime._execute_http("https://api.example.com/v1/tool", "POST", {}, 5)
        self.assertEqual(sent, [])

    def test_hosts_outside_the_allowlist_are_still_refused(self) -> None:
        with mock.patch.dict(os.environ, {"TOOL_HTTP_ALLOWLIST": "api.example.com"}):
            with self.assertRaisesRegex(ToolRuntimeError, "TOOL_HTTP_ALLOWLIST"):
                tool_runtime._execute_http("https://evil.example.net/x", "POST", {}, 5)

    def test_private_opt_in_and_requests_are_pinned_to_the_vetted_ip(self) -> None:
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, json={"ok": True})

        with mock.patch.dict(os.environ, {"TOOL_HTTP_ALLOWLIST": "internal.example.com", "TOOL_HTTP_ALLOW_PRIVATE": "true"}), \
                mock.patch("app.tool_runtime.socket.getaddrinfo", side_effect=_addrinfo("10.9.8.7")), \
                mock.patch("app.tool_runtime._http_client", self._mock_client(handler)):
            result = tool_runtime._execute_http("http://internal.example.com:8080/run?x=1", "POST", {"a": 1}, 5)
        self.assertEqual(result, {"status_code": 200, "content": {"ok": True}})
        self.assertEqual(sent[0].url.host, "10.9.8.7")
        self.assertEqual(sent[0].url.port, 8080)
        self.assertEqual(sent[0].url.query, b"x=1")
        self.assertEqual(sent[0].headers["host"], "internal.example.com:8080")

    def test_public_https_keeps_sni_for_certificate_checks(self) -> None:
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, text="plain body")

        with mock.patch.dict(os.environ, {"TOOL_HTTP_ALLOWLIST": "api.example.com", "TOOL_HTTP_ALLOW_PRIVATE": ""}), \
                mock.patch("app.tool_runtime.socket.getaddrinfo", side_effect=_addrinfo("93.184.216.34")), \
                mock.patch("app.tool_runtime._http_client", self._mock_client(handler)):
            result = tool_runtime._execute_http("https://api.example.com/v1/tool", "POST", {}, 5)
        self.assertEqual(result["content"], "plain body")
        self.assertEqual(sent[0].url.host, "93.184.216.34")
        self.assertEqual(sent[0].headers["host"], "api.example.com")
        self.assertEqual(sent[0].extensions.get("sni_hostname"), "api.example.com")

    def test_response_size_is_capped_by_header_and_while_streaming(self) -> None:
        responses = {
            "declared": lambda request: httpx.Response(200, content=b"x" * 2000),
            "chunked": lambda request: httpx.Response(200, content=iter([b"x" * 600, b"x" * 600, b"x" * 600])),
        }
        for label, handler in responses.items():
            with self.subTest(label), \
                    mock.patch.dict(os.environ, {"TOOL_HTTP_ALLOWLIST": "api.example.com", "TOOL_HTTP_MAX_BYTES": "1000"}), \
                    mock.patch("app.tool_runtime.socket.getaddrinfo", side_effect=_addrinfo("93.184.216.34")), \
                    mock.patch("app.tool_runtime._http_client", self._mock_client(handler)):
                with self.assertRaisesRegex(ToolRuntimeError, "TOOL_HTTP_MAX_BYTES"):
                    tool_runtime._execute_http("https://api.example.com/v1/tool", "POST", {}, 5)
        with mock.patch.dict(os.environ, {"TOOL_HTTP_ALLOWLIST": "api.example.com", "TOOL_HTTP_MAX_BYTES": "1000"}), \
                mock.patch("app.tool_runtime.socket.getaddrinfo", side_effect=_addrinfo("93.184.216.34")), \
                mock.patch("app.tool_runtime._http_client", self._mock_client(lambda request: httpx.Response(200, content=b"y" * 900))):
            self.assertEqual(len(tool_runtime._execute_http("https://api.example.com/v1/tool", "POST", {}, 5)["content"]), 900)


class GatewayHardeningApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        login = cls.client.post("/auth/login", json={"email": "admin@datapilot.local", "password": "ChangeMe123!"}).json()
        cls.headers = {"Authorization": f"Bearer {login['access_token']}"}
        cls.project_id = login["user"]["current_project_id"]
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
        # No Redis: the in-process limiter is what these tests exercise.
        self.redis_env = mock.patch.dict(os.environ, {"REDIS_URL": ""})
        self.redis_env.start()
        rate_limit.reset_client_cache()

    def tearDown(self) -> None:
        self.redis_env.stop()
        rate_limit.reset_client_cache()

    # --- helpers -----------------------------------------------------------------

    def _published_tool(self) -> dict:
        name = f"gateway.probe_{uuid4().hex[:8]}"
        tool = self.client.post("/query-tools", headers=self.headers, json={
            "name": name,
            "description": "Constant-result probe for gateway hardening tests.",
            "purpose": "Gateway hardening smoke test.",
            "data_source": "Local staging",
            "line_of_business": "Platform",
            "owner": "Platform Engineering",
            "tags": ["diagnostic"],
            "sql_template": "SELECT 1 AS ok",
            "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "allowed_relations": [],
            "row_limit": 1,
            "timeout_seconds": 5,
        })
        self.assertEqual(tool.status_code, 201, tool.text)
        self.assertEqual(self.client.post(f"/query-tools/{tool.json()['id']}/publish", headers=self.headers).status_code, 200)
        return tool.json()

    def _client_with_grant(self, tool: dict, daily_quota: int | None = None, expires_in_days: int | None = None) -> tuple[dict, dict]:
        body: dict = {"name": f"Hardening agent {uuid4().hex[:6]}", "scopes": ["tools:list", "tools:invoke"]}
        if expires_in_days is not None:
            body["expires_in_days"] = expires_in_days
        created = self.client.post("/external-clients", headers=self.headers, json=body)
        self.assertEqual(created.status_code, 201, created.text)
        grant = self.client.post(f"/query-tools/{tool['id']}/grants", headers=self.headers, json={"external_client_id": created.json()["id"], "enabled": True, "daily_quota": daily_quota})
        self.assertEqual(grant.status_code, 201, grant.text)
        self.assertEqual(grant.json()["daily_quota"], daily_quota)
        return created.json(), {"Authorization": f"Bearer {created.json()['token']}"}

    def _client_row(self, client_id: str) -> dict:
        return next(item for item in self.client.get("/external-clients", headers=self.headers).json() if item["id"] == client_id)

    # --- tool runtime ------------------------------------------------------------

    def test_builtin_handlers_honor_the_tool_timeout(self) -> None:
        def slow(db, parameters, project_id, user_id=None):
            time.sleep(5)
            return {"done": True}

        def reports_timeout(db, parameters, project_id, user_id=None):
            return {"timeout": tool_runtime._TOOL_TIMEOUT_SECONDS.get()}

        with mock.patch.dict(tool_runtime.BUILTIN_HANDLERS, {"test.slow": slow, "test.timeout": reports_timeout}), \
                mock.patch.object(tool_runtime, "_TIMEOUT_GRACE_SECONDS", 0.05):
            started = time.perf_counter()
            with self.assertRaisesRegex(ToolTimeoutError, "timed out after 1s"):
                with SessionLocal() as db:
                    # max_retries=2: a timeout must not be retried
                    execute_tool(db, "builtin", "test.slow", None, "POST", OPEN_SCHEMA, {}, self.project_id, 1, 2, 0)
            self.assertLess(time.perf_counter() - started, 3)
            result, attempts, _ = _run_builtin("test.timeout", {}, self.project_id, timeout_seconds=7)
        self.assertEqual(result, {"timeout": 7})
        self.assertEqual(attempts, 1)

    def test_sql_preview_is_scoped_to_the_projects_catalogued_datasets(self) -> None:
        reset_cache()
        with SessionLocal() as db:
            assets = db.scalars(select(DataAsset).where(DataAsset.project_id == self.project_id)).all()
            allowed = queryable_asset_ids(db, self.project_id, list(assets))
            asset = next((item for item in assets if item.id in allowed and item.connector_id is None), None)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE IF NOT EXISTS stray_uncatalogued (id INTEGER)"))
        for sql in ("SELECT * FROM stray_uncatalogued", "SELECT email FROM users", "SELECT * FROM other_project.secret_table"):
            with self.subTest(sql):
                with self.assertRaisesRegex(ToolRuntimeError, "catalogued datasets"):
                    _run_builtin("sql.preview", {"sql": sql}, self.project_id, schema=SQL_SCHEMA)
        with self.assertRaises(ToolRuntimeError):  # read-only guards still apply
            _run_builtin("sql.preview", {"sql": "DELETE FROM stray_uncatalogued"}, self.project_id, schema=SQL_SCHEMA)
        if asset is None:
            self.skipTest("no local catalogued asset in the demo project")
        relation = f"{asset.schema_name}.{asset.table_name}"
        result, _, _ = _run_builtin("sql.preview", {"sql": f"SELECT * FROM {relation}", "limit": 2}, self.project_id, schema=SQL_SCHEMA)
        self.assertIn("rows", result)
        # The same catalogued relation is outside another project's scope.
        with SessionLocal() as db:
            suffix = uuid4().hex[:6]
            other = Project(name=f"Other {suffix}", slug=f"other-{suffix}", description="scope probe", created_by=db.scalar(select(Project.created_by).where(Project.id == self.project_id)))
            db.add(other)
            db.commit()
            other_id = other.id
        with self.assertRaisesRegex(ToolRuntimeError, "catalogued datasets"):
            _run_builtin("sql.preview", {"sql": f"SELECT * FROM {relation}"}, other_id, schema=SQL_SCHEMA)

    # --- external clients --------------------------------------------------------

    def test_expired_clients_are_rejected_and_last_use_is_recorded(self) -> None:
        tool = self._published_tool()
        created, headers = self._client_with_grant(tool, expires_in_days=30)
        self.assertIsNotNone(created["expires_at"])
        self.assertIsNone(created["last_used_at"])
        self.assertFalse(created["expired"])
        listed = self.client.get("/external/v1/query-tools", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        row = self._client_row(created["id"])
        self.assertIsNotNone(row["last_used_at"])

        with SessionLocal() as db:
            client = db.get(ExternalClient, created["id"])
            client.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()
        expired = self.client.get("/external/v1/query-tools", headers=headers)
        self.assertEqual(expired.status_code, 401)
        self.assertIn("expired", expired.json()["detail"])
        mcp = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
        self.assertEqual(mcp.json()["error"]["data"]["http_status"], 401)
        self.assertTrue(self._client_row(created["id"])["expired"])

        rotated = self.client.post(f"/external-clients/{created['id']}/rotate", headers=self.headers, json={"expires_in_days": 7})
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertFalse(rotated.json()["expired"])
        new_headers = {"Authorization": f"Bearer {rotated.json()['token']}"}
        self.assertEqual(self.client.get("/external/v1/query-tools", headers=new_headers).status_code, 200)
        # Rotation without a body keeps working (and keeps the current expiry).
        again = self.client.post(f"/external-clients/{created['id']}/rotate", headers=self.headers)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["expires_at"][:16], rotated.json()["expires_at"][:16])
        self.assertEqual(self.client.post("/external-clients", headers=self.headers, json={"name": "bad", "expires_in_days": 0}).status_code, 422)

    def test_daily_quota_returns_429_once_exhausted(self) -> None:
        tool = self._published_tool()
        created, headers = self._client_with_grant(tool, daily_quota=2)
        path = f"/external/v1/query-tools/{tool['name']}/invoke"
        codes = [self.client.post(path, headers=headers, json={"parameters": {}}).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        limited = self.client.post(path, headers=headers, json={"parameters": {}})
        self.assertIn("Daily quota", limited.json()["detail"])
        self.assertIn("Retry-After", limited.headers)
        # Raising the quota on the grant lets the client continue today.
        self.client.post(f"/query-tools/{tool['id']}/grants", headers=self.headers, json={"external_client_id": created["id"], "enabled": True, "daily_quota": 3})
        self.assertEqual(self.client.post(path, headers=headers, json={"parameters": {}}).status_code, 200)
        grants = self.client.get(f"/query-tools/{tool['id']}/grants", headers=self.headers).json()
        self.assertEqual(grants[0]["daily_quota"], 3)

    def test_rate_limit_applies_to_listing_without_redis(self) -> None:
        tool = self._published_tool()
        _created, headers = self._client_with_grant(tool)
        with mock.patch("app.services.query_tools.EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE", 3):
            first = self.client.get("/external/v1/query-tools", headers=headers)
            mcp_list = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            invoke = self.client.post(f"/external/v1/query-tools/{tool['name']}/invoke", headers=headers, json={"parameters": {}})
            limited_list = self.client.get("/external/v1/query-tools", headers=headers)
            limited_mcp = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(first.status_code, 200)
        self.assertIn("result", mcp_list.json())
        self.assertEqual(invoke.status_code, 200, invoke.text)
        self.assertEqual(limited_list.status_code, 429)
        self.assertIn("Retry-After", limited_list.headers)
        self.assertEqual(limited_mcp.json()["error"]["data"]["http_status"], 429)

    # --- MCP ---------------------------------------------------------------------

    def test_mcp_ping_batch_notifications_and_unknown_methods(self) -> None:
        tool = self._published_tool()
        _created, headers = self._client_with_grant(tool)
        ping = self.client.post("/mcp", json={"jsonrpc": "2.0", "id": "p1", "method": "ping"})
        self.assertEqual(ping.status_code, 200)
        self.assertEqual(ping.json(), {"jsonrpc": "2.0", "id": "p1", "result": {}})

        notification = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(notification.status_code, 202)
        self.assertEqual(notification.content, b"")

        unknown = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 9, "method": "resources/list"})
        self.assertEqual(unknown.json()["error"]["code"], -32601)

        batch = self.client.post("/mcp", headers=headers, json=[
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": tool["name"], "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "nope"},
            {"jsonrpc": "2.0", "id": 5, "method": "ping"},
        ])
        self.assertEqual(batch.status_code, 200)
        answers = {item["id"]: item for item in batch.json()}
        self.assertEqual(sorted(answers), [1, 2, 3, 4, 5])
        self.assertEqual(answers[1]["result"]["protocolVersion"], "2025-03-26")
        self.assertIn(tool["name"], [item["name"] for item in answers[2]["result"]["tools"]])
        self.assertFalse(answers[3]["result"]["isError"])
        self.assertEqual(answers[4]["error"]["code"], -32601)
        self.assertEqual(answers[5]["result"], {})

        only_notifications = self.client.post("/mcp", headers=headers, json=[{"jsonrpc": "2.0", "method": "notifications/initialized"}])
        self.assertEqual(only_notifications.status_code, 202)
        self.assertEqual(only_notifications.content, b"")
        self.assertEqual(self.client.post("/mcp", json=[]).json()["error"]["code"], -32600)
        parse_error = self.client.post("/mcp", content=b"{not json", headers={"Content-Type": "application/json"})
        self.assertEqual(parse_error.json()["error"]["code"], -32700)

    # --- /query-tools/{id}/test --------------------------------------------------

    def test_query_tool_test_requires_query_runner_permission(self) -> None:
        tool = self._published_tool()
        email = f"viewer-{uuid4().hex[:8]}@datapilot.local"
        password = "ViewerPass123!"
        user = self.client.post("/admin/users", headers=self.headers, json={"name": "Gateway Viewer", "email": email, "temporary_password": password, "role": "viewer"})
        self.assertEqual(user.status_code, 201, user.text)
        membership = self.client.post(f"/projects/{self.project_id}/members", headers=self.headers, json={"user_id": user.json()["id"], "role": "viewer"})
        self.assertEqual(membership.status_code, 200, membership.text)
        login = self.client.post("/auth/login", json={"email": email, "password": password})
        viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        self.assertEqual(self.client.post(f"/projects/{self.project_id}/select", headers=viewer_headers).status_code, 200)

        denied = self.client.post(f"/query-tools/{tool['id']}/test", headers=viewer_headers, json={"parameters": {}})
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertIn("cannot run query tools", denied.json()["detail"])
        allowed = self.client.post(f"/query-tools/{tool['id']}/test", headers=self.headers, json={"parameters": {}})
        self.assertEqual(allowed.status_code, 200, allowed.text)
        audit = self.client.get("/audit", headers=self.headers)
        self.assertEqual(audit.status_code, 200, audit.text)
        self.assertIn("query_tool.test_denied", [item["event_type"] for item in audit.json()])


if __name__ == "__main__":
    unittest.main()
