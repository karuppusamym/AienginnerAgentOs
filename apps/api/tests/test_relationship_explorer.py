import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

# Own temp SQLite database, same pattern as test_new_endpoints.py.
database_file = Path(tempfile.gettempdir()) / f"datapilot-test-explorer-{uuid4().hex}.db"
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
from sqlalchemy import select

from app.connector_runtime import MetadataDiscovery, _group_columns
from app.database import SessionLocal, engine
from app.main import app
from app.models import DataAsset, LineageEdge, SemanticJoinPolicy, SemanticMetric
from app.services.relationships import VIEW_LINEAGE_PREFIX, view_dependencies
from app.services.sql_service import _catalog_sql_context

SUMMARY_VIEW = """ SELECT c.customer_id,
    c.first_name,
    count(o.order_id) AS order_count,
    COALESCE(sum(o.total_amount), (0)::numeric) AS lifetime_value
   FROM (demo.customers c
     LEFT JOIN demo.orders o ON ((o.customer_id = c.customer_id)))
  GROUP BY c.customer_id, c.first_name;"""
SEGMENT_VIEW = " SELECT count(*) AS customer_count, sum(s.lifetime_value) AS revenue FROM customer_order_summary s;"


def _discovery() -> MetadataDiscovery:
    rows = [
        ("demo", "customers", "customer_id", "integer", "NO"),
        ("demo", "customers", "first_name", "text", "YES"),
        ("demo", "customers", "email", "text", "YES"),
        ("demo", "orders", "order_id", "integer", "NO"),
        ("demo", "orders", "customer_id", "integer", "NO"),
        ("demo", "orders", "total_amount", "numeric", "NO"),
        ("demo", "customer_order_summary", "customer_id", "integer", "YES"),
        ("demo", "customer_order_summary", "first_name", "text", "YES"),
        ("demo", "customer_order_summary", "order_count", "bigint", "YES"),
        ("demo", "customer_order_summary", "lifetime_value", "numeric", "YES"),
        ("demo", "segment_revenue", "customer_count", "bigint", "YES"),
        ("demo", "segment_revenue", "revenue", "numeric", "YES"),
    ]
    return _group_columns(rows, {("demo", "customer_order_summary"): SUMMARY_VIEW, ("demo", "segment_revenue"): SEGMENT_VIEW})


class RelationshipExplorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        response = cls.client.post("/auth/login", json={"email": "admin@datapilot.local", "password": "ChangeMe123!"})
        cls.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        cls.project_id = next(item for item in cls.client.get("/projects", headers=cls.headers).json() if item["is_current"])["id"]
        cls.connector = cls.client.post(
            "/connectors", headers=cls.headers,
            json={"name": "Explorer Warehouse", "connector_type": "postgres", "host": "explorer.internal", "database": "demodb", "secret_reference": "env:EXPLORER_CREDS", "read_only": True},
        ).json()
        cls.other = cls.client.post(
            "/connectors", headers=cls.headers,
            json={"name": "Explorer Other", "connector_type": "postgres", "host": "other.internal", "database": "other", "secret_reference": "env:OTHER_CREDS", "read_only": True},
        ).json()
        cls._scan(_discovery())
        with SessionLocal() as db:
            assets = db.scalars(select(DataAsset).where(DataAsset.connector_id == cls.connector["id"])).all()
            cls.ids = {asset.table_name: asset.id for asset in assets}
            foreign = DataAsset(project_id=cls.project_id, connector_id=cls.other["id"], source_name="Explorer Other", schema_name="crm", table_name="contacts", asset_type="table", columns=[{"name": "customer_id", "type": "integer"}])
            db.add(foreign)
            db.flush()
            # Inserted directly: the API refuses cross-connector policies, but pre-existing ones must be flagged.
            db.add(SemanticJoinPolicy(project_id=cls.project_id, left_asset_id=cls.ids["customers"], right_asset_id=foreign.id, left_column="customer_id", right_column="customer_id", join_type="inner", status="approved", created_by=cls._admin_id(db)))
            db.commit()
            cls.foreign_id = foreign.id

    @staticmethod
    def _admin_id(db) -> str:
        from app.models import User
        return db.scalar(select(User.id).where(User.email == "admin@datapilot.local"))

    @classmethod
    def _scan(cls, discovery: MetadataDiscovery) -> dict:
        with patch("app.metadata_scan_runtime.discover_metadata", return_value=discovery):
            response = cls.client.post(f"/connectors/{cls.connector['id']}/scan", headers=cls.headers)
        assert response.status_code == 200, response.text
        return response.json()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        if database_file.exists():
            database_file.unlink()

    def _view_edges(self) -> list[LineageEdge]:
        with SessionLocal() as db:
            return db.scalars(select(LineageEdge).where(LineageEdge.project_id == self.project_id, LineageEdge.transformation.startswith(VIEW_LINEAGE_PREFIX))).all()

    def test_view_parser_handles_postgres_and_sqlserver_definitions(self) -> None:
        pg = view_dependencies(SUMMARY_VIEW, "postgres")
        self.assertEqual({(item["schema"], item["table"]) for item in pg}, {("demo", "customers"), ("demo", "orders")})
        orders = next(item for item in pg if item["table"] == "orders")
        self.assertIn({"source": "total_amount", "target": "lifetime_value"}, orders["columns"])
        tsql = view_dependencies("CREATE OR ALTER VIEW demo.v WITH SCHEMABINDING AS SELECT o.order_id, p.amount AS paid FROM demo.orders AS o JOIN demo.payments AS p ON p.order_id = o.order_id;", "sqlserver")
        self.assertEqual({(item["schema"], item["table"]) for item in tsql}, {("demo", "orders"), ("demo", "payments")})
        self.assertEqual(view_dependencies("not sql at all", "postgres"), [])

    def test_scan_records_views_and_base_table_lineage_idempotently(self) -> None:
        with SessionLocal() as db:
            summary = db.get(DataAsset, self.ids["customer_order_summary"])
            self.assertEqual(summary.asset_type, "view")
            self.assertEqual(db.get(DataAsset, self.ids["customers"]).asset_type, "table")
        edges = self._view_edges()
        pairs = {(edge.source_asset_id, edge.target_asset_id) for edge in edges}
        self.assertEqual(pairs, {
            (self.ids["customers"], self.ids["customer_order_summary"]),
            (self.ids["orders"], self.ids["customer_order_summary"]),
            (self.ids["customer_order_summary"], self.ids["segment_revenue"]),
        })
        self._scan(_discovery())
        self.assertEqual(len(self._view_edges()), 3, "a rescan must not duplicate view lineage")

    def test_overview_scopes_and_join_invariants(self) -> None:
        response = self.client.get(f"/semantic/explorer?scope=source&connector_id={self.connector['id']}", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["mode"], "overview")
        nodes = {node["id"]: node for node in payload["nodes"]}
        self.assertEqual(set(nodes), set(self.ids.values()))
        self.assertEqual(nodes[self.ids["customer_order_summary"]]["kind"], "view")
        self.assertEqual(nodes[self.ids["customers"]]["pii_column_count"], 2)
        self.assertTrue(nodes[self.ids["customers"]]["queryable"])
        by_type = {(edge["type"], frozenset((edge["source"], edge["target"]))) for edge in payload["edges"]}
        self.assertIn(("inferred_join", frozenset((self.ids["customers"], self.ids["orders"]))), by_type)
        self.assertNotIn(("inferred_join", frozenset((self.ids["customers"], self.ids["customer_order_summary"]))), by_type, "a view and its base table are lineage, not a join")
        lineage = [edge for edge in payload["edges"] if edge["type"] == "lineage"]
        self.assertEqual(len(lineage), 3)
        self.assertTrue(all(edge["origin"] == "view_definition" and not edge["cross_connector"] for edge in lineage))
        source = next(item for item in payload["sources"] if item["connector_id"] == self.connector["id"])
        self.assertEqual((source["asset_count"], source["view_count"]), (4, 2))

        everything = self.client.get("/semantic/explorer?scope=all", headers=self.headers).json()
        cross = [edge for edge in everything["edges"] if {edge["source"], edge["target"]} == {self.ids["customers"], self.foreign_id}]
        self.assertEqual([edge["type"] for edge in cross], ["governed_join"], "no inferred join may cross connectors")
        self.assertTrue(cross[0]["cross_connector"])
        self.assertGreaterEqual(everything["counts"]["cross_connector"], 1)

        grouped = self.client.get(f"/semantic/explorer?scope=group&focus={self.foreign_id}", headers=self.headers).json()
        self.assertEqual(grouped["group"], self.other["id"])
        self.assertEqual({node["id"] for node in grouped["nodes"]}, {self.foreign_id})

    def test_focus_layers_lineage_and_join_neighbours(self) -> None:
        shallow = self.client.get(f"/semantic/explorer?focus={self.ids['segment_revenue']}&depth=1&scope=source&connector_id={self.connector['id']}", headers=self.headers).json()
        levels = {node["id"]: node["level"] for node in shallow["nodes"]}
        self.assertEqual(levels, {self.ids["segment_revenue"]: 0, self.ids["customer_order_summary"]: -1})
        deep = self.client.get(f"/semantic/explorer?focus={self.ids['segment_revenue']}&depth=2", headers=self.headers).json()
        levels = {node["id"]: node["level"] for node in deep["nodes"]}
        self.assertEqual(levels[self.ids["customers"]], -2)
        self.assertEqual(levels[self.ids["orders"]], -2)

        base = self.client.get(f"/semantic/explorer?focus={self.ids['customers']}&depth=1", headers=self.headers).json()
        lanes = {node["id"]: node["lane"] for node in base["nodes"]}
        self.assertEqual(lanes[self.ids["customers"]], "focus")
        self.assertEqual(lanes[self.ids["customer_order_summary"]], "downstream")
        self.assertEqual(lanes[self.ids["orders"]], "join")
        self.assertEqual(lanes[self.foreign_id], "join", "a governed (even broken) policy is still a neighbour")

    def test_asset_detail_exposes_lineage_joins_metrics_and_llm_context(self) -> None:
        metric = self.client.post("/semantic/metrics", headers=self.headers, json={
            "asset_id": self.ids["customer_order_summary"], "name": "Customer lifetime value", "description": "Sum of order totals",
            "formula": "SUM(lifetime_value)", "grain": "customer", "owner": "analytics", "dimensions": ["first_name"], "synonyms": ["clv"], "status": "approved",
        })
        self.assertEqual(metric.status_code, 201, metric.text)
        response = self.client.get(f"/semantic/explorer/assets/{self.ids['customer_order_summary']}", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()
        self.assertEqual(detail["asset"]["kind"], "view")
        self.assertEqual({item["asset_id"] for item in detail["lineage"]["upstream"]}, {self.ids["customers"], self.ids["orders"]})
        self.assertEqual([item["asset_id"] for item in detail["lineage"]["downstream"]], [self.ids["segment_revenue"]])
        self.assertIn("demo.customers", detail["view_definition"])
        self.assertEqual([item["name"] for item in detail["metrics"]], ["Customer lifetime value"])
        with SessionLocal() as db:
            expected = _catalog_sql_context([db.get(DataAsset, self.ids["customer_order_summary"])])
        self.assertEqual(detail["llm_context"]["catalog_entry"], expected)
        self.assertTrue(detail["llm_context"]["queryable"])
        self.assertIn("Customer lifetime value", detail["llm_context"]["grounding_text"])
        self.assertIn("metrics", {check["key"] for check in detail["context_checks"]})

        customers = self.client.get(f"/semantic/explorer/assets/{self.ids['customers']}", headers=self.headers).json()
        joins = {join["other"]["id"]: join for join in customers["joins"]}
        self.assertEqual(joins[self.ids["orders"]]["type"], "inferred_join")
        self.assertEqual(joins[self.ids["orders"]]["column_pairs"], [{"this": "customer_id", "other": "customer_id"}])
        self.assertTrue(joins[self.foreign_id]["cross_connector"])
        self.assertEqual(customers["llm_context"]["grounding_text"], "", "a broken cross-connector policy is never sent to the model")
        with SessionLocal() as db:
            db.query(SemanticMetric).filter(SemanticMetric.id == metric.json()["id"]).delete()
            db.commit()

    def test_explorer_errors(self) -> None:
        self.assertEqual(self.client.get("/semantic/explorer?focus=missing", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get("/semantic/explorer?scope=source", headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get("/semantic/explorer?depth=4", headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get("/semantic/explorer/assets/missing", headers=self.headers).status_code, 404)


if __name__ == "__main__":
    unittest.main()
