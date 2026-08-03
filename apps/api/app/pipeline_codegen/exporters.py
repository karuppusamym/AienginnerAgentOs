from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from .emitters import PipelineArtifact
from .planner import PipelineGenerationError


@dataclass(slots=True)
class ExportedPackageFile:
    path: str
    content: str
    language: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExportedPackage:
    target: str
    root_dir: str
    archive_name: str
    files: list[ExportedPackageFile]

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "root_dir": self.root_dir,
            "archive_name": self.archive_name,
            "files": [item.as_dict() for item in self.files],
        }


def _normalize_export_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        raise PipelineGenerationError(f"Invalid artifact export path '{path}'", status_code=500)
    return normalized


def _package_slug(name: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in name).strip("-") or "pipeline"


def _scaffold_files(
    *,
    package_name: str,
    package_target: str,
    target_schema: str,
    target_table: str,
    source_count: int,
) -> list[ExportedPackageFile]:
    if package_target == "dbt":
        return [
            ExportedPackageFile(
                path="README.md",
                language="markdown",
                content=(
                    f"# {package_name}\n\n"
                    "Generated dbt package.\n\n"
                    "Suggested validation steps:\n"
                    "1. Configure a real `profiles.yml` for the target warehouse.\n"
                    "2. Run `dbt parse --project-dir . --profiles-dir <profiles-dir>`.\n"
                    "3. Run `dbt compile --project-dir . --profiles-dir <profiles-dir>`.\n"
                    "4. Run `dbt test --select %s` after a real execution environment is configured.\n"
                    % target_table
                ),
            ),
            ExportedPackageFile(
                path="profiles.example.yml",
                language="yaml",
                content=(
                    "datapilot_generated:\n"
                    "  target: dev\n"
                    "  outputs:\n"
                    "    dev:\n"
                    "      type: postgres\n"
                    "      host: localhost\n"
                    "      user: datapilot\n"
                    "      password: datapilot\n"
                    "      port: 5432\n"
                    "      dbname: datapilot\n"
                    f"      schema: {target_schema}\n"
                    "      threads: 1\n"
                ),
            ),
        ]
    if package_target == "dataform":
        return [
            ExportedPackageFile(
                path="package.json",
                language="json",
                content=(
                    "{\n"
                    f'  "name": "{_package_slug(package_name)}",\n'
                    '  "private": true,\n'
                    '  "dependencies": {\n'
                    '    "@dataform/core": "3.0.0"\n'
                    "  }\n"
                    "}\n"
                ),
            ),
            ExportedPackageFile(
                path="README.md",
                language="markdown",
                content=(
                    f"# {package_name}\n\n"
                    "Generated Dataform package.\n\n"
                    "Suggested validation steps:\n"
                    "1. Review `workflow_settings.yaml` and set the real project defaults.\n"
                    "2. Run `dataform compile` in this directory.\n"
                    "3. Run `dataform run` only after wiring real BigQuery credentials and project settings.\n"
                ),
            ),
            ExportedPackageFile(
                path="workflow_settings.yaml",
                language="yaml",
                content=(
                    f'defaultProject: "replace-with-project-id"\n'
                    f'defaultDataset: "{target_schema}"\n'
                    'defaultLocation: "US"\n'
                    f"defaultAssertionDataset: \"{target_schema}_assertions\"\n"
                    'dataformCoreVersion: "3.0.0"\n'
                ),
            ),
            ExportedPackageFile(
                path="definitions/_package_assertions.sqlx",
                language="sqlx",
                content=(
                    "config {\n"
                    '  type: "assertion",\n'
                    f'  name: "{target_table}_row_count_non_negative"\n'
                    "}\n\n"
                    "SELECT 1\n"
                    "WHERE (\n"
                    f"  SELECT COUNT(*)\n"
                    f"  FROM ${{ref(\"{target_table}\")}}\n"
                    ") < 0\n"
                ),
            ),
        ]
    if package_target == "postgres_view":
        return [
            ExportedPackageFile(
                path="README.md",
                language="markdown",
                content=(
                    f"# {package_name}\n\n"
                    f"Generated PostgreSQL deployment bundle for `{target_schema}.{target_table}` from {source_count} source dataset(s).\n"
                ),
            )
        ]
    raise PipelineGenerationError(f"Unsupported export target '{package_target}'", status_code=422)


def build_exported_package(
    *,
    pipeline_name: str,
    pipeline_version: int,
    package_target: str,
    target_schema: str,
    target_table: str,
    source_count: int,
    artifacts: list[dict[str, Any]],
    delivery_config: dict[str, Any] | None = None,
) -> ExportedPackage:
    selected = [
        PipelineArtifact(
            key=str(item["key"]),
            target=str(item["target"]),
            path=str(item["path"]),
            language=str(item["language"]),
            content=str(item["content"]),
            executable=bool(item.get("executable", False)),
            deployment_target=str(item["deployment_target"]) if item.get("deployment_target") else None,
        )
        for item in artifacts
        if str(item.get("target")) == package_target
    ]
    if not selected:
        raise PipelineGenerationError(
            f"No generated artifacts were found for target '{package_target}'",
            status_code=404,
        )
    slug = _package_slug(pipeline_name)
    root_dir = f"{slug}-{package_target}-v{pipeline_version}"
    files = [
        ExportedPackageFile(
            path=_normalize_export_path(artifact.path),
            content=artifact.content,
            language=artifact.language,
        )
        for artifact in selected
    ]
    files.extend(
        _scaffold_files(
            package_name=pipeline_name,
            package_target=package_target,
            target_schema=target_schema,
            target_table=target_table,
            source_count=source_count,
        )
    )
    files.append(
        ExportedPackageFile(
            path=".datapilot/package_manifest.json",
            language="json",
            content=json.dumps(
                {
                    "package_target": package_target,
                    "pipeline_name": pipeline_name,
                    "pipeline_version": pipeline_version,
                    "target_relation": f"{target_schema}.{target_table}",
                    "source_count": source_count,
                    "delivery_config": delivery_config or {},
                },
                indent=2,
            ),
        )
    )
    unique_paths: set[str] = set()
    ordered_files: list[ExportedPackageFile] = []
    for item in files:
        normalized = _normalize_export_path(item.path)
        if normalized in unique_paths:
            raise PipelineGenerationError(
                f"Duplicate export path '{normalized}' for target '{package_target}'",
                status_code=500,
            )
        unique_paths.add(normalized)
        ordered_files.append(
            ExportedPackageFile(path=normalized, content=item.content, language=item.language)
        )
    return ExportedPackage(
        target=package_target,
        root_dir=root_dir,
        archive_name=f"{root_dir}.zip",
        files=ordered_files,
    )


def materialize_exported_package(package: ExportedPackage, destination: Path) -> Path:
    root = destination / package.root_dir
    root.mkdir(parents=True, exist_ok=True)
    for item in package.files:
        file_path = root / Path(item.path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(item.content, encoding="utf-8")
    return root


def create_package_archive(package: ExportedPackage) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for item in package.files:
            archive.writestr(f"{package.root_dir}/{item.path}", item.content)
    return buffer.getvalue()
