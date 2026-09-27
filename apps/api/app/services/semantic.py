"""Semantic join-policy validation."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Connector, DataAsset
from ..schemas import SemanticJoinPolicyCreate


def validate_semantic_join_policy(
    db: Session, project_id: str, payload: SemanticJoinPolicyCreate
) -> None:
    if payload.left_asset_id == payload.right_asset_id:
        raise HTTPException(status_code=422, detail="A join policy must reference two different datasets")
    assets = [db.get(DataAsset, payload.left_asset_id), db.get(DataAsset, payload.right_asset_id)]
    if any(asset is None or asset.project_id != project_id for asset in assets):
        raise HTTPException(status_code=404, detail="A join-policy dataset was not found in this project")
    left, right = assets
    assert left is not None and right is not None
    # A join policy is a promise that DataPilot can actually execute this
    # join -- but every /sql/generate or /sql/execute call is scoped to one
    # connector (or the local workspace) at a time (see routers/sql.py's
    # allowed_asset_ids), so a policy joining two different external
    # connectors' assets can never be run by anything that reads it, no
    # matter how well the columns line up. Locally-staged/uploaded assets
    # (connector_id is None) are exempt from this check: they really do all
    # live in the same local Postgres/SQLite database and can genuinely be
    # joined in one query. Caught here, at creation/update time, rather than
    # left to silently sit in the catalog as an approved policy nothing can
    # honor -- found by reading the semantic graph UI's own inferred-edge
    # output, which had no equivalent guard either (see /semantic/graph).
    if left.connector_id and right.connector_id:
        if left.connector_id != right.connector_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{left.schema_name}.{left.table_name} and {right.schema_name}.{right.table_name} "
                    "belong to two different connectors. A join policy can only reference datasets that "
                    "can be queried through the same connector (or both from the local workspace) -- "
                    "DataPilot has no way to execute a join across two separate connectors."
                ),
            )
        # Same connector_id isn't automatically joinable: an MCP-backed
        # connector's assets are individually-discovered tools (see
        # discover_mcp_metadata), and MCP execution (execute_connector_query
        # -> execute_mcp_tool) always invokes exactly one named tool per
        # call -- there is no cross-tool join path anywhere in the runtime.
        # A single MCP toolbox can even front multiple distinct physical
        # backends with no structured signal telling us which tools share
        # one (see infra/mcp-toolbox/toolbox.yaml's two "kind: source"
        # blocks), so two MCP tools under the same connector still can't be
        # joined in one query even when they happen to share a backend.
        # Direct-driver connectors are unaffected: those really do share one
        # physical DB connection, so same-connector joins stay allowed.
        connector = db.get(Connector, left.connector_id)
        if connector is not None and connector.connection_mode == "mcp":
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{left.schema_name}.{left.table_name} and {right.schema_name}.{right.table_name} "
                    "are two different MCP tools on the same connector. Each MCP-backed connector call "
                    "invokes exactly one named tool, so DataPilot has no way to join two separate MCP "
                    "tool results in a single query -- even when they're on the same connector."
                ),
            )
    left_columns = set(column_names_for_asset(left))
    right_columns = set(column_names_for_asset(right))
    if payload.left_column not in left_columns:
        raise HTTPException(status_code=422, detail=f"Column {payload.left_column} is not present on {left.schema_name}.{left.table_name}")
    if payload.right_column not in right_columns:
        raise HTTPException(status_code=422, detail=f"Column {payload.right_column} is not present on {right.schema_name}.{right.table_name}")


def column_names_for_asset(asset: DataAsset) -> list[str]:
    return [str(column.get("name", "")).strip() for column in asset.columns if str(column.get("name", "")).strip()]
