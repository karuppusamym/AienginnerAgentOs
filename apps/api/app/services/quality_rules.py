"""Quality rule creation (record + versioned internal artifact)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import DataAsset, QualityRule, User
from .audit import save_internal_artifact_version


def create_quality_rule_record(
    db: Session,
    user: User,
    asset: DataAsset,
    name: str,
    rule_type: str,
    column_name: str,
    config: dict[str, Any],
    severity: str,
) -> QualityRule:
    rule = QualityRule(
        project_id=asset.project_id,
        asset_id=asset.id,
        name=name,
        rule_type=rule_type,
        column_name=column_name,
        config=config,
        severity=severity,
        created_by=user.id,
    )
    db.add(rule)
    db.flush()
    definition = {
        "dataset": f"{asset.schema_name}.{asset.table_name}",
        "name": name,
        "rule_type": rule_type,
        "column_name": column_name,
        "config": config,
        "severity": severity,
    }
    artifact, _ = save_internal_artifact_version(
        db,
        user,
        name,
        "quality_rule",
        json.dumps(definition, indent=2),
        {"quality_rule_id": rule.id, "asset_id": asset.id},
    )
    rule.artifact_id = artifact.id
    return rule
