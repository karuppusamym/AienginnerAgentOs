from __future__ import annotations

from .emitters import PipelineArtifact
from .planner import PipelineGenerationError, PipelineSpec


def validate_pipeline_spec(spec: PipelineSpec) -> None:
    if not spec.sources:
        raise PipelineGenerationError("A pipeline must include at least one source dataset", status_code=422)
    if not spec.output_columns:
        raise PipelineGenerationError("The pipeline projection is empty", status_code=422)
    output_names = [str(column.get("name", "")).strip() for column in spec.output_columns]
    if any(not name for name in output_names):
        raise PipelineGenerationError("The pipeline output contains an unnamed column", status_code=422)
    if len(output_names) != len(set(output_names)):
        raise PipelineGenerationError("The pipeline output contains duplicate column names", status_code=409)
    for join in spec.joins:
        if join.join_type not in {"inner", "left"}:
            raise PipelineGenerationError(f"Unsupported join type '{join.join_type}'", status_code=422)


def validate_pipeline_artifacts(artifacts: list[PipelineArtifact]) -> None:
    if not artifacts:
        raise PipelineGenerationError("No pipeline artifacts were generated", status_code=500)
    paths = [artifact.path for artifact in artifacts]
    if len(paths) != len(set(paths)):
        raise PipelineGenerationError("Generated artifact paths must be unique", status_code=500)
    if not any(artifact.key == "postgres_view" for artifact in artifacts):
        raise PipelineGenerationError("A deployable PostgreSQL artifact is required", status_code=500)
    for artifact in artifacts:
        if not artifact.content.strip():
            raise PipelineGenerationError(
                f"Generated artifact '{artifact.path}' is empty",
                status_code=500,
            )
