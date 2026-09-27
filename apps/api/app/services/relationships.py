"""Relationship explorer: typed lineage/join graph around a focus asset, per-asset
context detail, and view -> base-table lineage captured during metadata scans.

"Group" means assets DataPilot can query together in one call (see
``asset_group_key``). Join edges -- governed or inferred -- are only ever
suggested inside one group; a governed policy that crosses groups is kept but
flagged ``cross_connector`` so the UI can show it as broken. Lineage edges are
data flow, not joins, so they may legitimately cross sources (an external
extraction stages a connector table into the local workspace).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable, Literal

import sqlglot
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlglot import exp

from ..grounding import grounding_prompt_text
from ..metadata_generation import is_unreviewed_description
from ..models import Connector, DataAsset, LineageEdge, SemanticJoinPolicy, SemanticMetric
from ..sql_guard import DIALECTS
from .semantic import column_names_for_asset
from .sql_service import _catalog_sql_context, connector_dialect

LOCAL_GROUP = "__local__"
VIEW_LINEAGE_PREFIX = "View definition: "
INFERRED_SKIP_COLUMNS = {"id", "created_at", "updated_at"}
FOCUS_NODE_LIMIT = 150
OVERVIEW_NODE_LIMIT = 500

ExplorerScope = Literal["all", "source", "group"]


def asset_group_key(asset: DataAsset, connectors_by_id: dict[str, Connector]) -> str:
    """Bucket of assets that one /sql/generate or /sql/execute call can reach.

    One bucket per direct-driver connector, one shared bucket for local
    workspace assets, and one bucket *per asset* for MCP connectors: MCP
    execution invokes exactly one named tool per call, and one toolbox can
    front several physical backends, so two MCP tools are never joinable.
    """
    if not asset.connector_id:
        return LOCAL_GROUP
    connector = connectors_by_id.get(asset.connector_id)
    if connector is not None and connector.connection_mode == "mcp":
        return f"{asset.connector_id}:{asset.id}"
    return asset.connector_id


def asset_kind(asset: DataAsset, connector: Connector | None) -> str:
    if connector is not None and connector.connection_mode == "mcp":
        return "mcp_tool"
    if asset.asset_type in {"staged_file", "imported"}:
        return "file"
    if asset.asset_type == "view":
        return "view"
    if asset.asset_type == "virtual_query":
        return "query"
    return "table"


def lineage_origin(edge: LineageEdge) -> str:
    if edge.pipeline_id:
        return "pipeline"
    transformation = edge.transformation or ""
    if transformation.startswith(VIEW_LINEAGE_PREFIX):
        return "view_definition"
    if transformation.startswith("Read-only external extraction"):
        return "extraction"
    return "lineage"


# --- view definitions -> base tables -------------------------------------------------

_CREATE_VIEW_BODY = re.compile(r"\bAS\s+((?:WITH|SELECT)\b.*)$", re.IGNORECASE | re.DOTALL)


def _view_query(definition: str, dialect: str) -> exp.Expression | None:
    read = DIALECTS.get(dialect, dialect)
    text = definition.strip().rstrip(";")
    body = _CREATE_VIEW_BODY.search(text)
    for candidate in (text, body.group(1) if body else None):
        if not candidate:
            continue
        try:
            parsed = sqlglot.parse_one(candidate, read=read)
        except Exception:
            continue
        if isinstance(parsed, exp.Create):
            parsed = parsed.expression
        if isinstance(parsed, exp.Query):
            return parsed
    return None


def view_dependencies(definition: str, dialect: str) -> list[dict[str, Any]]:
    """Base relations a view reads, with a best-effort outer-projection column mapping.

    ``definition`` may be a bare SELECT (Postgres ``pg_views.definition``) or a
    full ``CREATE VIEW ... AS SELECT`` (SQL Server ``sys.sql_modules``).
    """
    query = _view_query(definition, dialect)
    if query is None:
        return []
    cte_names = {cte.alias_or_name.lower() for cte in query.find_all(exp.CTE)}
    tables: dict[tuple[str | None, str], dict[str, Any]] = {}
    aliases: dict[str, tuple[str | None, str]] = {}
    for table in query.find_all(exp.Table):
        name = str(table.name or "")
        if not name or name.lower() in cte_names:
            continue
        key = (str(table.db or "") or None, name)
        tables.setdefault(key, {"schema": key[0], "table": name, "columns": []})
        aliases[str(table.alias_or_name or name).lower()] = key
    if isinstance(query, exp.Select):
        for projection in query.expressions:
            target = projection.alias_or_name
            for column in projection.find_all(exp.Column):
                qualifier = str(column.table or "").lower()
                key = aliases.get(qualifier) if qualifier else (next(iter(tables)) if len(tables) == 1 else None)
                mapping = {"source": column.name, "target": target}
                if key and target and column.name and mapping not in tables[key]["columns"]:
                    tables[key]["columns"].append(mapping)
    return list(tables.values())


def sync_view_lineage(db: Session, connector: Connector, view: DataAsset, definition: str, connector_assets: Iterable[DataAsset]) -> int:
    """Upsert ``base table -> view`` lineage edges for one scanned view; returns the edge count.

    Idempotent: edges are keyed by source relation, stale ones (a base table the
    view no longer reads) are removed, and a base table that is not catalogued
    still gets an edge with ``source_asset_id`` NULL so the gap is visible.
    """
    dialect = connector_dialect(connector, "postgres")
    by_relation: dict[tuple[str, str], DataAsset] = {}
    by_table: dict[str, list[DataAsset]] = defaultdict(list)
    for asset in connector_assets:
        by_relation[(asset.schema_name.lower(), asset.table_name.lower())] = asset
        by_table[asset.table_name.lower()].append(asset)
    default_schemas = [view.schema_name.lower(), "dbo" if dialect == "sqlserver" else "public"]
    wanted: dict[str, tuple[str, DataAsset | None, list[dict[str, Any]]]] = {}
    for dependency in view_dependencies(definition, dialect):
        table = dependency["table"].lower()
        if dependency["schema"]:
            source = by_relation.get((dependency["schema"].lower(), table))
        else:
            source = next((by_relation[(schema, table)] for schema in default_schemas if (schema, table) in by_relation), None)
            if source is None and len(by_table[table]) == 1:
                source = by_table[table][0]
        if source is not None and source.id == view.id:
            continue
        relation = f"{source.schema_name}.{source.table_name}" if source else f"{dependency['schema'] or default_schemas[1]}.{dependency['table']}"
        wanted[relation.lower()] = (relation, source, dependency["columns"])
    transformation = f"{VIEW_LINEAGE_PREFIX}{definition.strip()[:8000]}"
    target_relation = f"{view.schema_name}.{view.table_name}"
    existing = db.scalars(
        select(LineageEdge).where(
            LineageEdge.project_id == view.project_id,
            LineageEdge.target_asset_id == view.id,
            LineageEdge.pipeline_id.is_(None),
            LineageEdge.transformation.startswith(VIEW_LINEAGE_PREFIX),
        )
    ).all()
    for edge in existing:
        match = wanted.pop(edge.source_relation.lower(), None)
        if match is None:
            db.delete(edge)
            continue
        relation, source, columns = match
        edge.source_asset_id = source.id if source else None
        edge.source_relation = relation
        edge.target_relation = target_relation
        edge.transformation = transformation
        edge.column_mapping = columns
    for relation, source, columns in wanted.values():
        db.add(LineageEdge(
            project_id=view.project_id,
            source_asset_id=source.id if source else None,
            target_asset_id=view.id,
            source_relation=relation,
            target_relation=target_relation,
            transformation=transformation,
            column_mapping=columns,
        ))
    db.flush()
    return len(existing) + len(wanted)


# --- project catalog snapshot ---------------------------------------------------------


class _Catalog:
    def __init__(self, db: Session, project_id: str) -> None:
        self.project_id = project_id
        self.assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project_id).order_by(DataAsset.schema_name, DataAsset.table_name)).all()
        self.by_id = {asset.id: asset for asset in self.assets}
        self.connectors = {connector.id: connector for connector in db.scalars(select(Connector).where(Connector.project_id == project_id)).all()}
        self.policies = db.scalars(select(SemanticJoinPolicy).where(SemanticJoinPolicy.project_id == project_id)).all()
        self.lineage = db.scalars(select(LineageEdge).where(LineageEdge.project_id == project_id).order_by(LineageEdge.created_at)).all()
        bare = [f"{asset.schema_name}.{asset.table_name}" for asset in self.assets]
        duplicates = {relation for relation in bare if bare.count(relation) > 1}
        self.relations = {asset.id: f"{relation} ({self.source_label(asset)})" if relation in duplicates else relation for asset, relation in zip(self.assets, bare)}
        self._by_relation: dict[str, list[DataAsset]] = defaultdict(list)
        for asset, relation in zip(self.assets, bare):
            self._by_relation[relation.lower()].append(asset)

    def connector(self, asset: DataAsset) -> Connector | None:
        return self.connectors.get(asset.connector_id) if asset.connector_id else None

    def group(self, asset: DataAsset) -> str:
        return asset_group_key(asset, self.connectors)

    def source_label(self, asset: DataAsset) -> str:
        connector = self.connector(asset)
        return connector.name if connector else "local catalog"

    def resolve(self, asset_id: str | None, relation: str) -> str | None:
        if asset_id and asset_id in self.by_id:
            return asset_id
        candidates = self._by_relation.get(relation.lower(), [])
        if len(candidates) == 1:
            return candidates[0].id
        # Pipelines and extractions write into the local workspace.
        local = [asset for asset in candidates if not asset.connector_id]
        return local[0].id if len(local) == 1 else None

    def node(self, asset: DataAsset, queryable: set[str]) -> dict[str, Any]:
        connector = self.connector(asset)
        columns = [column for column in asset.columns if column.get("name")]
        return {
            "id": asset.id,
            "relation": self.relations[asset.id],
            "schema_name": asset.schema_name,
            "table_name": asset.table_name,
            "source_label": self.source_label(asset),
            "connector_id": asset.connector_id,
            "connector_type": connector.connector_type if connector else "local_files",
            "connection_mode": connector.connection_mode if connector else "direct",
            "group": self.group(asset),
            "asset_type": asset.asset_type,
            "kind": asset_kind(asset, connector),
            "row_count": asset.row_count,
            "metadata_status": asset.metadata_status,
            "sensitivity": asset.sensitivity,
            "column_count": len(columns),
            "pii_column_count": sum(1 for column in columns if column.get("sensitivity") == "pii" or column.get("pii_category")),
            "described": not is_unreviewed_description(asset.description),
            "queryable": asset.id in queryable,
        }

    def lineage_edges(self, asset_ids: set[str]) -> list[dict[str, Any]]:
        edges: dict[tuple[str, str], dict[str, Any]] = {}
        for edge in self.lineage:
            source = self.resolve(edge.source_asset_id, edge.source_relation)
            target = self.resolve(edge.target_asset_id, edge.target_relation)
            if not source or not target or source == target or source not in asset_ids or target not in asset_ids:
                continue
            key = (source, target)
            if key in edges:
                edges[key]["record_count"] += 1
                continue
            source_asset, target_asset = self.by_id[source], self.by_id[target]
            edges[key] = {
                "id": f"lineage:{edge.id}",
                "type": "lineage",
                "source": source,
                "target": target,
                "origin": lineage_origin(edge),
                "columns": [{"left": str(item.get("source", "")), "right": str(item.get("target", ""))} for item in (edge.column_mapping or []) if isinstance(item, dict)],
                "cross_connector": self.group(source_asset) != self.group(target_asset),
                "record_count": 1,
            }
        return list(edges.values())

    def join_edges(self, asset_ids: set[str], include_inferred: bool, lineage_pairs: set[frozenset[str]]) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        governed_pairs: set[tuple[frozenset[str], str, str]] = set()
        for policy in self.policies:
            if policy.left_asset_id not in asset_ids or policy.right_asset_id not in asset_ids:
                continue
            left, right = self.by_id[policy.left_asset_id], self.by_id[policy.right_asset_id]
            governed_pairs.add((frozenset((left.id, right.id)), policy.left_column, policy.right_column))
            governed_pairs.add((frozenset((left.id, right.id)), policy.right_column, policy.left_column))
            edges.append({
                "id": f"policy:{policy.id}",
                "type": "governed_join",
                "source": left.id,
                "target": right.id,
                "columns": [{"left": policy.left_column, "right": policy.right_column}],
                "join_type": policy.join_type,
                "status": policy.status,
                "description": policy.description,
                "cross_connector": self.group(left) != self.group(right),
            })
        if not include_inferred:
            return edges
        by_group: dict[str, list[DataAsset]] = defaultdict(list)
        for asset in self.assets:
            if asset.id in asset_ids:
                by_group[self.group(asset)].append(asset)
        for members in by_group.values():
            names = [set(column_names_for_asset(asset)) for asset in members]
            for index, left in enumerate(members):
                for offset, right in enumerate(members[index + 1:], start=index + 1):
                    pair = frozenset((left.id, right.id))
                    # A view shares its base table's columns by construction; that is lineage, not a join.
                    if pair in lineage_pairs:
                        continue
                    shared = sorted(
                        column for column in names[index] & names[offset]
                        if column.lower() not in INFERRED_SKIP_COLUMNS and (pair, column, column) not in governed_pairs
                    )
                    if shared:
                        edges.append({
                            "id": f"inferred:{left.id}:{right.id}",
                            "type": "inferred_join",
                            "source": left.id,
                            "target": right.id,
                            "columns": [{"left": column, "right": column} for column in shared],
                            "join_type": "inner",
                            "status": "suggested",
                            "cross_connector": False,
                        })
        return edges


def _scope_assets(catalog: _Catalog, scope: ExplorerScope, connector_id: str | None, group: str | None) -> list[DataAsset]:
    if scope == "source":
        wanted = None if connector_id in {None, "", LOCAL_GROUP} else connector_id
        return [asset for asset in catalog.assets if asset.connector_id == wanted]
    if scope == "group":
        return [asset for asset in catalog.assets if catalog.group(asset) == group]
    return list(catalog.assets)


def _sources_summary(catalog: _Catalog) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}
    for asset in catalog.assets:
        connector = catalog.connector(asset)
        key = asset.connector_id or LOCAL_GROUP
        source = sources.setdefault(key, {
            "key": key,
            "connector_id": asset.connector_id,
            "label": catalog.source_label(asset),
            "connector_type": connector.connector_type if connector else "local_files",
            "connection_mode": connector.connection_mode if connector else "direct",
            "asset_count": 0,
            "view_count": 0,
            "groups": set(),
        })
        source["asset_count"] += 1
        source["view_count"] += asset.asset_type == "view"
        group = catalog.group(asset)
        source["groups"].add(group)
        entry = groups.setdefault(group, {"group": group, "source_key": key, "source_label": source["label"], "asset_count": 0})
        entry["asset_count"] += 1
    source_list = [{**{k: v for k, v in item.items() if k != "groups"}, "group_count": len(item["groups"])} for item in sources.values()]
    source_list.sort(key=lambda item: (item["key"] == LOCAL_GROUP, item["label"].lower()))
    return source_list, sorted(groups.values(), key=lambda item: (item["source_label"].lower(), item["group"]))


def explorer_graph(
    db: Session,
    project_id: str,
    *,
    focus: str | None,
    depth: int,
    scope: ExplorerScope,
    connector_id: str | None,
    group: str | None,
    include_inferred: bool,
    queryable: set[str],
) -> dict[str, Any]:
    catalog = _Catalog(db, project_id)
    focus_asset = catalog.by_id.get(focus) if focus else None
    if focus and focus_asset is None:
        raise LookupError("Focus asset not found in the current project")
    if scope == "group" and not group:
        if focus_asset is None:
            raise ValueError("Group scope needs a group or a focus asset")
        group = catalog.group(focus_asset)
    if scope == "source" and connector_id is None and focus_asset is not None:
        connector_id = focus_asset.connector_id or LOCAL_GROUP
    if scope == "source" and connector_id is None:
        raise ValueError("Source scope needs a connector_id (or __local__)")
    scoped = _scope_assets(catalog, scope, connector_id, group)
    if focus_asset is not None and focus_asset not in scoped:
        scoped.append(focus_asset)
    scoped_ids = {asset.id for asset in scoped}
    lineage = catalog.lineage_edges(scoped_ids)
    lineage_pairs = {frozenset((edge["source"], edge["target"])) for edge in lineage}
    joins = catalog.join_edges(scoped_ids, include_inferred, lineage_pairs)

    placement: dict[str, dict[str, Any]] = {}
    if focus_asset is not None:
        placement[focus_asset.id] = {"level": 0, "lane": "focus", "distance": 0}
        downstream: dict[str, set[str]] = defaultdict(set)
        upstream: dict[str, set[str]] = defaultdict(set)
        for edge in lineage:
            downstream[edge["source"]].add(edge["target"])
            upstream[edge["target"]].add(edge["source"])
        for sign, adjacency, lane in ((-1, upstream, "upstream"), (1, downstream, "downstream")):
            frontier, seen = [focus_asset.id], {focus_asset.id}
            for hop in range(1, depth + 1):
                following = []
                for current in frontier:
                    for neighbour in sorted(adjacency[current]):
                        if neighbour in seen:
                            continue
                        seen.add(neighbour)
                        following.append(neighbour)
                        placement.setdefault(neighbour, {"level": sign * hop, "lane": lane, "distance": hop})
                frontier = following
        joined: dict[str, set[str]] = defaultdict(set)
        for edge in joins:
            joined[edge["source"]].add(edge["target"])
            joined[edge["target"]].add(edge["source"])
        frontier, seen = [focus_asset.id], {focus_asset.id}
        for hop in range(1, depth + 1):
            following = []
            for current in frontier:
                for neighbour in sorted(joined[current]):
                    if neighbour in seen:
                        continue
                    seen.add(neighbour)
                    following.append(neighbour)
                    placement.setdefault(neighbour, {"level": 0, "lane": "join", "distance": hop})
            frontier = following
        ordered = sorted(placement, key=lambda asset_id: (placement[asset_id]["distance"], catalog.relations[asset_id].lower()))
        shown_ids = set(ordered[:FOCUS_NODE_LIMIT])
        total = len(placement)
    else:
        ordered = [asset.id for asset in scoped]
        shown_ids = set(ordered[:OVERVIEW_NODE_LIMIT])
        total = len(ordered)

    nodes = []
    for asset_id in ordered:
        if asset_id not in shown_ids:
            continue
        node = catalog.node(catalog.by_id[asset_id], queryable)
        node.update(placement.get(asset_id, {"level": None, "lane": None, "distance": None}))
        nodes.append(node)
    edges = [edge for edge in (*lineage, *joins) if edge["source"] in shown_ids and edge["target"] in shown_ids]
    sources, groups = _sources_summary(catalog)
    return {
        "project_id": project_id,
        "mode": "focus" if focus_asset is not None else "overview",
        "focus": focus_asset.id if focus_asset is not None else None,
        "depth": depth,
        "scope": scope,
        "connector_id": connector_id,
        "group": group,
        "include_inferred": include_inferred,
        "nodes": nodes,
        "edges": edges,
        "sources": sources,
        "groups": groups,
        "counts": {
            "nodes": len(nodes),
            "lineage": sum(1 for edge in edges if edge["type"] == "lineage"),
            "governed_join": sum(1 for edge in edges if edge["type"] == "governed_join"),
            "inferred_join": sum(1 for edge in edges if edge["type"] == "inferred_join"),
            "cross_connector": sum(1 for edge in edges if edge["type"] != "lineage" and edge["cross_connector"]),
        },
        "total_in_scope": total,
        "truncated": total > len(nodes),
    }


def _context_checks(asset: DataAsset, joins: list[dict[str, Any]], metrics: list[dict[str, Any]], queryable: bool) -> list[dict[str, Any]]:
    columns = [column for column in asset.columns if column.get("name")]
    total = len(columns) or 1
    named = sum(1 for column in columns if column.get("business_name"))
    described = sum(1 for column in columns if column.get("description"))
    pii = [column for column in columns if column.get("sensitivity") == "pii" or column.get("pii_category")]
    governed = [join for join in joins if join["type"] == "governed_join" and join["status"] == "approved" and not join["cross_connector"]]
    return [
        {"key": "queryable", "label": "Queryable by SQL generation", "ok": queryable, "detail": "Included in the catalog sent to the model for its source." if queryable else "Catalogued only -- no physical table to query yet (stage the file first)."},
        {"key": "description", "label": "Reviewed table description", "ok": not is_unreviewed_description(asset.description), "detail": asset.metadata_status},
        {"key": "business_names", "label": "Columns with business names", "ok": named == len(columns) and bool(columns), "detail": f"{named}/{len(columns)} ({round(100 * named / total)}%)"},
        {"key": "column_descriptions", "label": "Columns with descriptions", "ok": described == len(columns) and bool(columns), "detail": f"{described}/{len(columns)} ({round(100 * described / total)}%)"},
        {"key": "pii", "label": "PII classified", "ok": asset.sensitivity != "unclassified" or not pii, "detail": f"{len(pii)} PII column(s); table sensitivity {asset.sensitivity}"},
        {"key": "joins", "label": "Approved join paths", "ok": bool(governed), "detail": f"{len(governed)} approved" + (f", {sum(1 for join in joins if join['type'] == 'inferred_join')} inferred suggestion(s)" if joins else "")},
        {"key": "metrics", "label": "Bound semantic metrics", "ok": bool(metrics), "detail": f"{len(metrics)} metric(s)"},
    ]


def explorer_asset_detail(db: Session, project_id: str, asset_id: str, *, include_inferred: bool, queryable: set[str]) -> dict[str, Any]:
    catalog = _Catalog(db, project_id)
    asset = catalog.by_id.get(asset_id)
    if asset is None:
        raise LookupError("Dataset not found in the current project")
    node = catalog.node(asset, queryable)
    # Joins are only meaningful inside the asset's own group; governed policies are
    # listed regardless so a broken cross-connector one is still visible.
    same_group = {item.id for item in catalog.assets if catalog.group(item) == catalog.group(asset)}
    policy_ids = {
        side for policy in catalog.policies if asset.id in (policy.left_asset_id, policy.right_asset_id)
        for side in (policy.left_asset_id, policy.right_asset_id) if side in catalog.by_id
    }
    lineage_all = catalog.lineage_edges(set(catalog.by_id))
    lineage_pairs = {frozenset((edge["source"], edge["target"])) for edge in lineage_all}
    joins = []
    for edge in catalog.join_edges(same_group | policy_ids | {asset.id}, include_inferred, lineage_pairs):
        if asset.id not in (edge["source"], edge["target"]):
            continue
        outgoing = edge["source"] == asset.id
        other = catalog.by_id[edge["target"] if outgoing else edge["source"]]
        joins.append({
            **edge,
            "other": {"id": other.id, "relation": catalog.relations[other.id], "source_label": catalog.source_label(other), "kind": asset_kind(other, catalog.connector(other))},
            "column_pairs": [{"this": pair["left"] if outgoing else pair["right"], "other": pair["right"] if outgoing else pair["left"]} for pair in edge["columns"]],
        })
    joins.sort(key=lambda item: (item["type"] != "governed_join", item["other"]["relation"].lower()))

    upstream, downstream, view_definition = [], [], None
    for edge in catalog.lineage:
        source = catalog.resolve(edge.source_asset_id, edge.source_relation)
        target = catalog.resolve(edge.target_asset_id, edge.target_relation)
        if asset.id not in (source, target) or source == target:
            continue
        is_upstream = target == asset.id
        other_id = source if is_upstream else target
        other = catalog.by_id.get(other_id) if other_id else None
        origin = lineage_origin(edge)
        if is_upstream and origin == "view_definition" and view_definition is None:
            view_definition = edge.transformation[len(VIEW_LINEAGE_PREFIX):]
        (upstream if is_upstream else downstream).append({
            "edge_id": edge.id,
            "asset_id": other.id if other else None,
            "relation": catalog.relations[other.id] if other else (edge.source_relation if is_upstream else edge.target_relation),
            "source_label": catalog.source_label(other) if other else None,
            "kind": asset_kind(other, catalog.connector(other)) if other else None,
            "origin": origin,
            "transformation": None if origin == "view_definition" else edge.transformation,
            "column_mapping": [item for item in (edge.column_mapping or []) if isinstance(item, dict)],
        })

    metrics = [
        {"id": metric.id, "name": metric.name, "description": metric.description, "formula": metric.formula, "grain": metric.grain, "owner": metric.owner, "dimensions": metric.dimensions, "synonyms": metric.synonyms, "status": metric.status}
        for metric in db.scalars(select(SemanticMetric).where(SemanticMetric.project_id == project_id, SemanticMetric.asset_id == asset.id).order_by(SemanticMetric.name)).all()
    ]
    is_queryable = asset.id in queryable
    # Same shapes grounding_context() hands to grounding_prompt_text(): approved joins
    # (only ones the model may actually use) and this table's metrics.
    grounding = {
        "semantic_matches": [metric for metric in metrics if metric["status"] != "deprecated"],
        "join_matches": [
            {
                "left_relation": f"{catalog.by_id[join['source']].schema_name}.{catalog.by_id[join['source']].table_name}",
                "right_relation": f"{catalog.by_id[join['target']].schema_name}.{catalog.by_id[join['target']].table_name}",
                "left_column": join["columns"][0]["left"],
                "right_column": join["columns"][0]["right"],
                "join_type": join["join_type"],
            }
            for join in joins
            if join["type"] == "governed_join" and join["status"] == "approved" and not join["cross_connector"]
        ],
    }
    return {
        "asset": {
            **node,
            "description": asset.description,
            "owner": asset.owner,
            "tags": asset.tags,
            "freshness_sla_hours": asset.freshness_sla_hours,
            "columns": asset.columns,
        },
        "joins": joins,
        "lineage": {"upstream": upstream, "downstream": downstream},
        "view_definition": view_definition,
        "metrics": metrics,
        "llm_context": {
            "queryable": is_queryable,
            "catalog_entry": _catalog_sql_context([asset]),
            "grounding_text": grounding_prompt_text(grounding) if grounding["semantic_matches"] or grounding["join_matches"] else "",
        },
        "context_checks": _context_checks(asset, joins, metrics, is_queryable),
    }
