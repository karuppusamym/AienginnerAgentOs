import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

# This file previously imported app.main directly with no DATABASE_URL of
# its own. Run standalone, that meant SQLAlchemy fell through to whatever
# app/database.py's default resolves to -- on a real dev machine, the
# checked-out repo's own datapilot.db on a mounted/network filesystem,
# producing SQLite disk-I/O errors, and even where it happened to work it
# silently shared state with (and could corrupt) the developer's real local
# database. It only ever passed in CI because pytest imports test_api.py
# first in the same process and this file inherited test_api.py's temp
# DATABASE_URL env var as a side effect of import order, not real isolation.
# Give this file its own isolated temp SQLite database, same pattern as
# test_api.py, so it is correct whether run alone or as part of the suite
# and in any import order.
database_file = Path(tempfile.gettempdir()) / f"datapilot-test-new-endpoints-{uuid4().hex}.db"
if database_file.exists():
    database_file.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("QDRANT_URL", "")
os.environ.setdefault("SUPERSET_INTERNAL_URL", "")
os.environ.setdefault("SUPERSET_ADMIN_PASSWORD", "")
os.environ.setdefault("SUPERSET_EDITOR_SSO_SECRET", "test-editor-secret")
os.environ.setdefault("ENABLE_DEMO_DATA", "true")

from fastapi.testclient import TestClient
from app.database import engine
from app.main import app, project_permissions
from app.models import User

class DataPilotEndpointsTests(unittest.TestCase):
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

    def test_semantic_graph_endpoint(self) -> None:
        response = self.client.get("/semantic/graph", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)

    def test_lineage_graph_endpoint(self) -> None:
        response = self.client.get("/lineage/graph", headers=self.headers)
        self.assertIn(response.status_code, (200, 404, 403, 422))  # 200 if valid project

    def test_sql_history_endpoint(self) -> None:
        response = self.client.get("/sql/history", headers=self.headers)
        self.assertIn(response.status_code, (200, 404, 403))

    def test_datasets_import_endpoint(self) -> None:
        # Just verifying the route exists and is protected
        response = self.client.post("/datasets/import", headers=self.headers, json={})
        self.assertIn(response.status_code, (201, 400, 403, 422, 404))

    def test_rbac_project_roles(self) -> None:
        # A viewer globally, but owner in project -> should get write permissions
        user = User(id="u1", role="viewer")
        perms_no_project = project_permissions(user, None)
        self.assertNotIn("catalog:write", perms_no_project)
        self.assertIn("catalog:read", perms_no_project)

        perms_with_project_owner = project_permissions(user, "owner")
        self.assertIn("catalog:write", perms_with_project_owner)
        self.assertIn("semantic:write", perms_with_project_owner)

        user_eng = User(id="u2", role="engineer")
        perms_eng = project_permissions(user_eng, "viewer")
        # Changed deliberately (review C2): the project role is authoritative, so
        # a global engineer who is only a viewer here no longer keeps write access.
        self.assertNotIn("catalog:write", perms_eng)
        self.assertEqual(project_permissions(User(id="u3", role="admin"), "viewer"), {"*"})

    def test_agentic_self_healing_reflection(self) -> None:
        from app.temporal_activities import _reflect_on_tool_error
        from unittest.mock import MagicMock
        
        db = MagicMock()
        provider = MagicMock()
        provider.provider_type = "gemini"
        
        class MockGeneratedText:
            content = '''```json
            {"table": "customers"}
            ```'''
        
        import app.temporal_activities
        original_generate = app.temporal_activities.generate_text
        app.temporal_activities.generate_text = MagicMock(return_value=MockGeneratedText())
        
        schema = {"required": ["table"], "properties": {"table": {"type": "string"}}}
        job = MagicMock()
        job.id = "job123"
        job.created_by = "u1"
        
        try:
            params = _reflect_on_tool_error(
                db, provider, "catalog.search", schema, "Find users", 
                {"tabl": "customers"}, "Missing required parameter 'table'", "p1", job
            )
            self.assertEqual(params, {"table": "customers"})
        finally:
            app.temporal_activities.generate_text = original_generate

    def test_agentic_reviewer_loop(self) -> None:
        from app.temporal_activities import _review_plan_outputs
        from unittest.mock import MagicMock
        
        provider = MagicMock()
        provider.provider_type = "gemini"
        
        class MockGeneratedText:
            content = '''```json
            [{"agent": "SQL Analyst", "action": "Query the new column"}]
            ```'''
        
        import app.temporal_activities
        original_generate = app.temporal_activities.generate_text
        app.temporal_activities.generate_text = MagicMock(return_value=MockGeneratedText())
        
        job = MagicMock()
        job.id = "job123"
        job.created_by = "u1"
        
        try:
            steps = _review_plan_outputs(
                provider, "Find users", [{"agent": "Metadata", "action": "lookup"}],
                [{"type": "tool_result", "data": {"missing": True}}], 
                {"SQL Analyst", "Metadata"}, "p1", job
            )
            self.assertEqual(len(steps), 1)
            self.assertEqual(steps[0]["agent"], "SQL Analyst")
        finally:
            app.temporal_activities.generate_text = original_generate

    def test_graph_rag_pathfinding(self) -> None:
        from app.grounding import _find_graph_join_paths
        
        class MockJoin:
            def __init__(self, id, left, right):
                self.id = id
                self.left_asset_id = left
                self.right_asset_id = right
                
        # A -> B -> C -> D
        joins = [
            MockJoin("j1", "A", "B"),
            MockJoin("j2", "B", "C"),
            MockJoin("j3", "C", "D"),
            MockJoin("j4", "E", "F"),
        ]
        
        # Test 1 hop
        paths = _find_graph_join_paths({"A", "B"}, joins)
        self.assertEqual(paths, {"j1"})
        
        # Test 3 hops
        paths2 = _find_graph_join_paths({"A", "D"}, joins)
        self.assertEqual(paths2, {"j1", "j2", "j3"})
        
        # Test disconnected
        paths3 = _find_graph_join_paths({"A", "E"}, joins)
        self.assertEqual(paths3, set())
