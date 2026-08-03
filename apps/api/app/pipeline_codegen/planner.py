from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import Connector, DataAsset, SemanticJoinPolicy
from ..staging import safe_identifier


SUPPORTED_ARTIFACT_TARGETS = ("postgres_view", "dbt", "dataform")
DEFAULT_ARTIFACT_TARGETS = list(SUPPORTED_ARTIFACT_TARGETS)


class PipelineGenerationError(Exception):
    def __init__(self, detail: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(slots=True)
class PipelineSource:
    asset_id: str
    relation: str
    schema_name: str
    table_name: str
    physical_relation: str
    columns: list[dict[str, Any]]
    connector_id: str | None
    alias: str


@dataclass(slots=True)
class ProjectionField:
    asset_id: str
    source_relation: str
    source_table: str
    source_column: str
    output_name: str
    alias: str
    column: dict[str, Any]


@dataclass(slots=True)
class PipelineJoin:
    left_relation: str
    right_relation: str
    left_key: str
    right_key: str
    join_type: str
    policy_id: str | None
    source: str
    right_alias: str
    right_asset_id: str


@dataclass(slots=True)
class PipelineSpec:
    objective: str
    target_schema: str
    target_table: str
    target_relation: str
    artifact_targets: list[str]
    sources: list[PipelineSource]
    projections: list[ProjectionField]
    joins: list[PipelineJoin]
    output_columns: list[dict[str, Any]]
    source_column_mappings: dict[str, list[dict[str, str]]]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, str]]
    checks: list[str]
    deployment: dict[str, Any]


def normalize_artifact_targets(targets: list[str] | None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for target in targets or DEFAULT_ARTIFACT_TARGETS:
        if target not in SUPPORTED_ARTIFACT_TARGETS:
            supported = ", ".join(SUPPORTED_ARTIFACT_TARGETS)
            raise PipelineGenerationError(
                f"Unsupported pipeline artifact target '{target}'. Supported targets: {supported}",
                status_code=422,
            )
        if target not in seen:
            ordered.append(target)
            seen.add(target)
    if "postgres_view" not in seen:
        ordered.insert(0, "postgres_view")
    return ordered


def _relation_name(asset: DataAsset) -> str:
    return f"{asset.schema_name}.{asset.table_name}"


def _physical_relation(asset: DataAsset) -> str:
    schema_name = safe_identifier(asset.schema_name, "public")
    table_name = safe_identifier(asset.table_name, "source_data")
    return f'"{schema_name}"."{table_name}"'


def _column_names(asset: DataAsset) -> list[str]:
    return [
        str(column.get("name", "")).strip()
        for column in asset.columns
        if str(column.get("name", "")).strip()
    ]


def plan_pipeline(
    *,
    objective: str,
    assets: list[DataAsset],
    approved_join_policies: list[SemanticJoinPolicy],
    connectors_by_id: dict[str, Connector | None],
    target_schema: str,
    target_table: str,
    artifact_targets: list[str] | None,
) -> PipelineSpec:
    if not assets:
        raise PipelineGenerationError("At least one source dataset is required", status_code=422)

    normalized_targets = normalize_artifact_targets(artifact_targets)
    safe_target_schema = safe_identifier(target_schema, "curated")
    safe_target_table = safe_identifier(target_table, "pipeline_output")
    assets_by_id = {asset.id: asset for asset in assets}
    sources = [
        PipelineSource(
            asset_id=asset.id,
            relation=_relation_name(asset),
            schema_name=asset.schema_name,
            table_name=asset.table_name,
            physical_relation=_physical_relation(asset),
            columns=asset.columns,
            connector_id=asset.connector_id,
            alias=f"s{index + 1}",
        )
        for index, asset in enumerate(assets)
    ]

    projections: list[ProjectionField] = []
    pipeline_columns: list[dict[str, Any]] = []
    source_column_mappings: dict[str, list[dict[str, str]]] = {
        source.asset_id: [] for source in sources
    }
    used_names: set[str] = set()
    for source in sources:
        for column_name in _column_names(assets_by_id[source.asset_id]):
            safe_column_name = safe_identifier(column_name, "column")
            candidate_name = (
                safe_column_name
                if safe_column_name not in used_names
                else f"{safe_identifier(source.table_name, 'source')}_{safe_column_name}"
            )
            output_name = safe_identifier(candidate_name, "column")
            used_names.add(output_name)
            column_metadata = next(
                (
                    item
                    for item in source.columns
                    if str(item.get("name", "")).strip() == column_name
                ),
                {},
            )
            projections.append(
                ProjectionField(
                    asset_id=source.asset_id,
                    source_relation=source.relation,
                    source_table=source.table_name,
                    source_column=column_name,
                    output_name=output_name,
                    alias=source.alias,
                    column=column_metadata,
                )
            )
            pipeline_columns.append({**column_metadata, "name": output_name})
            source_column_mappings[source.asset_id].append(
                {"source": column_name, "target": output_name}
            )

    joins: list[PipelineJoin] = []
    primary = assets[0]
    primary_columns = set(_column_names(primary))
    primary_relation = sources[0].relation
    if len(assets) > 1:
        for index, asset in enumerate(assets[1:], start=1):
            source = sources[index]
            right_relation = source.relation
            policy = next(
                (
                    item
                    for item in approved_join_policies
                    if {item.left_asset_id, item.right_asset_id} == {primary.id, asset.id}
                ),
                None,
            )
            if policy:
                if policy.left_asset_id == primary.id:
                    left_key, right_key = policy.left_column, policy.right_column
                else:
                    left_key, right_key = policy.right_column, policy.left_column
                if policy.join_type == "left" and policy.left_asset_id != primary.id:
                    raise PipelineGenerationError(
                        f"Approved left join policy {policy.id} requires {right_relation} to be selected before {primary_relation}"
                    )
                join_type = policy.join_type
                policy_id = policy.id
                join_source = "semantic_policy"
            else:
                candidates = sorted(
                    name
                    for name in primary_columns.intersection(_column_names(asset))
                    if name.lower() == "id" or name.lower().endswith("_id")
                )
                if not candidates:
                    raise PipelineGenerationError(
                        f"No safe shared identifier was found between {primary_relation} and {right_relation}; define and approve a semantic join policy before generating this pipeline"
                    )
                left_key = right_key = candidates[0]
                join_type = "inner"
                policy_id = None
                join_source = "inferred_identifier"
            joins.append(
                PipelineJoin(
                    left_relation=primary_relation,
                    right_relation=right_relation,
                    left_key=left_key,
                    right_key=right_key,
                    join_type=join_type,
                    policy_id=policy_id,
                    source=join_source,
                    right_alias=source.alias,
                    right_asset_id=source.asset_id,
                )
            )

    executable = all(
        source.connector_id is None
        or (
            connectors_by_id.get(source.connector_id) is not None
            and connectors_by_id[source.connector_id].host == "mock-sqlserver"
        )
        for source in sources
    )
    checks = [
        "source relation exists",
        "output schema matches governed projection",
        "row count is non-negative",
    ]
    if joins:
        checks.append("semantic policy or shared identifier join validated")
    nodes = [
        *[
            {
                "id": f"source_{index + 1}",
                "type": "source",
                "label": source.relation,
                "asset_id": source.asset_id,
            }
            for index, source in enumerate(sources)
        ],
        {"id": "transform", "type": "sql", "label": "Versioned SQL transformation"},
        {"id": "quality", "type": "quality", "label": "Schema and row-count validation"},
        {"id": "publish", "type": "target", "label": f"{safe_target_schema}.{safe_target_table}"},
    ]
    edges = [
        *[
            {"source": f"source_{index + 1}", "target": "transform"}
            for index in range(len(sources))
        ],
        {"source": "transform", "target": "quality"},
        {"source": "quality", "target": "publish"},
    ]
    deployment = {
        "requires_approval": True,
        "executable": executable,
        "reason": (
            "local PostgreSQL sources only"
            if executable
            else "external source pipelines require connector-runner deployment"
        ),
        "supported_targets": normalized_targets,
        "primary_artifact": "postgres_view",
    }
    return PipelineSpec(
        objective=objective,
        target_schema=safe_target_schema,
        target_table=safe_target_table,
        target_relation=f"{safe_target_schema}.{safe_target_table}",
        artifact_targets=normalized_targets,
        sources=sources,
        projections=projections,
        joins=joins,
        output_columns=pipeline_columns,
        source_column_mappings=source_column_mappings,
        nodes=nodes,
        edges=edges,
        checks=checks,
        deployment=deployment,
    )
