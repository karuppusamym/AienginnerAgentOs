from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..staging import safe_identifier
from .planner import PipelineJoin, PipelineSource, PipelineSpec


@dataclass(slots=True)
class PipelineArtifact:
    key: str
    target: str
    path: str
    language: str
    content: str
    executable: bool = False
    deployment_target: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _postgres_projection_sql(spec: PipelineSpec) -> str:
    lines = [
        f'{projection.alias}."{safe_identifier(projection.source_column, "column")}" AS "{safe_identifier(projection.output_name, "column")}"'
        for projection in spec.projections
    ]
    return ",\n  ".join(lines)


def _postgres_join_sql(join: PipelineJoin, sources_by_asset: dict[str, PipelineSource]) -> str:
    right_source = sources_by_asset[join.right_asset_id]
    join_keyword = "LEFT JOIN" if join.join_type == "left" else "INNER JOIN"
    return (
        f'{join_keyword} {right_source.physical_relation} {right_source.alias} '
        f'ON s1."{safe_identifier(join.left_key, "key")}" = '
        f'{right_source.alias}."{safe_identifier(join.right_key, "key")}"'
    )


def render_postgres_select(spec: PipelineSpec) -> str:
    sources_by_asset = {source.asset_id: source for source in spec.sources}
    join_sql = "\n".join(
        _postgres_join_sql(join, sources_by_asset) for join in spec.joins
    )
    sql = (
        "SELECT\n"
        f"  {_postgres_projection_sql(spec)}\n"
        f"FROM {spec.sources[0].physical_relation} s1"
    )
    if join_sql:
        sql += f"\n{join_sql}"
    return sql


def emit_postgres_artifact(spec: PipelineSpec) -> PipelineArtifact:
    select_sql = render_postgres_select(spec)
    content = (
        f'CREATE OR REPLACE VIEW "{spec.target_schema}"."{spec.target_table}" AS\n'
        f"{select_sql};"
    )
    return PipelineArtifact(
        key="postgres_view",
        target="postgres_view",
        path=f"sql/{spec.target_schema}/{spec.target_table}.sql",
        language="sql",
        content=content,
        executable=True,
        deployment_target="postgresql",
    )


def _dbt_source_reference(source: PipelineSource) -> str:
    return '{{ source("%s", "%s") }}' % (
        safe_identifier(source.schema_name, "source_schema"),
        safe_identifier(source.table_name, "source_table"),
    )


def _dbt_model_sql(spec: PipelineSpec) -> str:
    lines = [
        "{{ config(materialized='view', schema='%s') }}" % spec.target_schema,
        "",
        "select",
    ]
    projections = [
        f'  {projection.alias}."{safe_identifier(projection.source_column, "column")}" as "{safe_identifier(projection.output_name, "column")}"'
        for projection in spec.projections
    ]
    lines.append(",\n".join(projections))
    lines.append(f"from {_dbt_source_reference(spec.sources[0])} as s1")
    sources_by_asset = {source.asset_id: source for source in spec.sources}
    for join in spec.joins:
        right_source = sources_by_asset[join.right_asset_id]
        join_keyword = "left join" if join.join_type == "left" else "inner join"
        lines.append(
            f"{join_keyword} {_dbt_source_reference(right_source)} as {right_source.alias} "
            f'on s1."{safe_identifier(join.left_key, "key")}" = {right_source.alias}."{safe_identifier(join.right_key, "key")}"'
        )
    return "\n".join(lines)


def _yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dbt_source_properties(spec: PipelineSpec) -> str:
    grouped: dict[str, list[str]] = {}
    for source in spec.sources:
        grouped.setdefault(safe_identifier(source.schema_name, "source_schema"), []).append(
            safe_identifier(source.table_name, "source_table")
        )
    lines = ["version: 2", "", "sources:"]
    for schema_name, tables in grouped.items():
        lines.append(f"  - name: {schema_name}")
        lines.append(
            f"    description: {_yaml_quote(f'Generated source schema for {schema_name}')}"
        )
        lines.append("    tables:")
        for table_name in sorted(set(tables)):
            lines.append(f"      - name: {table_name}")
    return "\n".join(lines)


def _dbt_model_properties(spec: PipelineSpec) -> str:
    join_output_columns: set[str] = set()
    for join in spec.joins:
        for source in spec.sources:
            if source.relation == join.left_relation:
                join_output_columns.update(
                    mapping["target"]
                    for mapping in spec.source_column_mappings[source.asset_id]
                    if mapping["source"] == join.left_key
                )
            if source.relation == join.right_relation:
                join_output_columns.update(
                    mapping["target"]
                    for mapping in spec.source_column_mappings[source.asset_id]
                    if mapping["source"] == join.right_key
                )
    lines = [
        "version: 2",
        "",
        "models:",
        f"  - name: {spec.target_table}",
        f"    description: {_yaml_quote(spec.objective)}",
        "    columns:",
    ]
    for column in spec.output_columns:
        name = safe_identifier(str(column.get("name", "column")), "column")
        description = column.get("description") or f"Projected output column {name}"
        lines.append(f"      - name: {name}")
        lines.append(f"        description: {_yaml_quote(str(description))}")
        if name in join_output_columns:
            lines.append("        tests:")
            lines.append("          - not_null")
    return "\n".join(lines)


def emit_dbt_artifacts(spec: PipelineSpec) -> list[PipelineArtifact]:
    project_name = safe_identifier(f"{spec.target_table}_pipeline", "generated_pipeline")
    return [
        PipelineArtifact(
            key="dbt_project",
            target="dbt",
            path="dbt_project.yml",
            language="yaml",
            content=(
                f"name: {project_name}\n"
                'version: "1.0.0"\n'
                "config-version: 2\n\n"
                'profile: "datapilot_generated"\n\n'
                'model-paths: ["models"]\n'
            ),
        ),
        PipelineArtifact(
            key="dbt_model",
            target="dbt",
            path=f"models/{spec.target_schema}/{spec.target_table}.sql",
            language="sql",
            content=_dbt_model_sql(spec),
        ),
        PipelineArtifact(
            key="dbt_sources",
            target="dbt",
            path=f"models/{spec.target_schema}/_sources.yml",
            language="yaml",
            content=_dbt_source_properties(spec),
        ),
        PipelineArtifact(
            key="dbt_model_properties",
            target="dbt",
            path=f"models/{spec.target_schema}/{spec.target_table}.yml",
            language="yaml",
            content=_dbt_model_properties(spec),
        ),
    ]


def _dataform_projection_sql(spec: PipelineSpec) -> str:
    return ",\n  ".join(
        f"{projection.alias}.{safe_identifier(projection.source_column, 'column')} AS {safe_identifier(projection.output_name, 'column')}"
        for projection in spec.projections
    )


def _dataform_ref(source: PipelineSource) -> str:
    return '${ref("%s", "%s")}' % (
        safe_identifier(source.schema_name, "source_schema"),
        safe_identifier(source.table_name, "source_table"),
    )


def emit_dataform_artifacts(spec: PipelineSpec) -> list[PipelineArtifact]:
    lines = [
        "config {",
        '  type: "view",',
        f'  schema: "{spec.target_schema}",',
        f'  name: "{spec.target_table}",',
        '  tags: ["generated", "governed"]',
        "}",
        "",
        "SELECT",
        f"  {_dataform_projection_sql(spec)}",
        f"FROM {_dataform_ref(spec.sources[0])} AS s1",
    ]
    sources_by_asset = {source.asset_id: source for source in spec.sources}
    for join in spec.joins:
        right_source = sources_by_asset[join.right_asset_id]
        join_keyword = "LEFT JOIN" if join.join_type == "left" else "INNER JOIN"
        lines.append(
            f"{join_keyword} {_dataform_ref(right_source)} AS {right_source.alias} "
            f"ON s1.{safe_identifier(join.left_key, 'key')} = {right_source.alias}.{safe_identifier(join.right_key, 'key')}"
        )
    artifacts = [
        PipelineArtifact(
            key="dataform_model",
            target="dataform",
            path=f"definitions/{spec.target_table}.sqlx",
            language="sqlx",
            content="\n".join(lines),
        )
    ]
    for source in spec.sources:
        declaration_name = (
            f"{safe_identifier(source.schema_name, 'source_schema')}_"
            f"{safe_identifier(source.table_name, 'source_table')}_declaration"
        )
        artifacts.append(
            PipelineArtifact(
                key=(
                    f"dataform_source_{safe_identifier(source.schema_name, 'source_schema')}_"
                    f"{safe_identifier(source.table_name, 'source_table')}"
                ),
                target="dataform",
                path=f"definitions/{declaration_name}.sqlx",
                language="sqlx",
                content=(
                    "config {\n"
                    '  type: "declaration",\n'
                    f'  schema: "{safe_identifier(source.schema_name, "source_schema")}",\n'
                    f'  name: "{safe_identifier(source.table_name, "source_table")}"\n'
                    "}"
                ),
            )
        )
    return artifacts


def emit_pipeline_artifacts(spec: PipelineSpec) -> list[PipelineArtifact]:
    artifacts: list[PipelineArtifact] = [emit_postgres_artifact(spec)]
    if "dbt" in spec.artifact_targets:
        artifacts.extend(emit_dbt_artifacts(spec))
    if "dataform" in spec.artifact_targets:
        artifacts.extend(emit_dataform_artifacts(spec))
    return artifacts
