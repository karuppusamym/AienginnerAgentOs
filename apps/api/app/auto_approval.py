"""Auto-approval policy agent: approves only low-risk, reversible, read-only requests.

Deterministic checks decide; no model is consulted. An approval qualifies only
when its action type is on the allowlist and every check for that type passes.
Anything that writes or deletes data, touches PII, reaches an external system,
or changes runtime behaviour stays with a human. Every verdict (approve or
defer) is stored on the approval as ``evidence.auto_review`` and audited, and
an auto-approval is recorded as the policy's decision (``decided_by`` empty,
``approval.auto_approved`` audit event), never as a person's.

The switch is per project (``projects.settings.auto_approval.enabled``) and
off by default.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import sqlglot
from sqlglot import exp
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .governance import record_audit_event
from .models import Approval, Artifact, ArtifactVersion, AuditEvent, DataAsset, Project, User
from .pii import pii_category
from .sql_guard import check_read_only

POLICY_VERSION = 1
AUTO_APPROVABLE_ACTIONS = {"publish_superset_query"}
# Why each other action type always needs a person.
MANUAL_ONLY_REASONS = {
    "agent_execution": "Agent runs can take consequential or external actions",
    "tool_execution": "The tool is flagged for approval and may write or call external systems",
    "apply_retention": "Retention permanently deletes records",
    "deploy_pipeline": "Deploying a pipeline writes data",
    "create_index": "Index DDL changes the database",
    "enable_ingestion_schedule": "Ingestion schedules write data on a timer",
    "schedule_workflow": "Schedules run unattended writes",
    "quality_remediation": "Remediation changes or drops data",
    "prompt_activation": "Prompt activation changes how every SQL answer is generated",
}
EXTERNAL_OR_WRITE_WORDS = re.compile(
    r"\b(copy|export|send|e-?mail|share|shared drive|upload|transfer|sync|delete|drop|truncate|purge|grant|external|marketing|download)\b",
    re.IGNORECASE,
)


def auto_approval_enabled(project: Project) -> bool:
    return bool(((project.settings or {}).get("auto_approval") or {}).get("enabled"))


def set_auto_approval(project: Project, enabled: bool) -> None:
    settings = dict(project.settings or {})
    settings["auto_approval"] = {**(settings.get("auto_approval") or {}), "enabled": bool(enabled)}
    project.settings = settings


def separation_of_duties() -> bool:
    return os.getenv("APPROVAL_SEPARATION_OF_DUTIES", "false").strip().lower() in {"1", "true", "yes", "on"}


def _approved_sql(db: Session, project: Project, evidence: dict[str, Any]) -> str | None:
    """The SQL of the immutable artifact version the request names (what an approval would publish)."""
    artifact = db.get(Artifact, str(evidence.get("artifact_id", "")))
    version = db.scalar(select(ArtifactVersion).where(ArtifactVersion.artifact_id == str(evidence.get("artifact_id", "")), ArtifactVersion.version == int(evidence.get("artifact_version", 0) or 0)))
    if artifact is None or artifact.project_id != project.id or version is None:
        return None
    source_type = str(evidence.get("source_type", ""))
    if source_type == "sql_artifact" and artifact.artifact_type == "sql":
        return version.content
    if source_type == "notebook_sql_cell" and artifact.artifact_type == "notebook":
        cells = json.loads(version.content).get("cells", [])
        return next((str(cell.get("source", "")) for cell in reversed(cells) if cell.get("type") == "sql" and str(cell.get("source", "")).strip()), None)
    return None


def _pii_columns(db: Session, project: Project, sql: str, relations: list[tuple[str | None, str]], output_columns: list[Any]) -> tuple[list[str], list[str]]:
    """(PII columns referenced or returned, relations missing from the catalog)."""
    assets: list[DataAsset] = []
    missing: list[str] = []
    for schema, table in relations:
        statement = select(DataAsset).where(DataAsset.project_id == project.id, func.lower(DataAsset.table_name) == table)
        if schema:
            statement = statement.where(func.lower(DataAsset.schema_name) == schema)
        found = db.scalars(statement).all()
        if not found:
            missing.append(f"{schema}.{table}" if schema else table)
        assets.extend(found)
    catalog_pii = {
        str(column.get("name", "")).lower()
        for asset in assets
        for column in asset.columns or []
        if column.get("sensitivity") == "pii" or column.get("pii_category")
    }
    names: set[str] = set()
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
        names |= {str(column.name).lower() for column in tree.find_all(exp.Column) if column.name}
        if any(True for _ in tree.find_all(exp.Star)):
            names |= {str(column.get("name", "")).lower() for asset in assets for column in asset.columns or []}
    except Exception:
        names.add("*unparsed*")
    names |= {str(item.get("name") if isinstance(item, dict) else item).lower() for item in output_columns or []}
    flagged = sorted(name for name in names if name in catalog_pii or pii_category(name))
    return flagged, missing


def evaluate(db: Session, project: Project, approval: Approval) -> dict[str, Any]:
    """Run the policy's checks. Returns {"eligible", "reason", "checks": [{"check", "passed", "detail"}]}."""
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> bool:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        return passed

    def verdict(reason: str) -> dict[str, Any]:
        eligible = all(item["passed"] for item in checks)
        return {"eligible": eligible, "reason": reason, "checks": checks}

    evidence = approval.evidence or {}
    if not check("pending request", approval.status == "pending", approval.status):
        return verdict("Already decided")
    if not check("allowlisted read-only action", approval.action_type in AUTO_APPROVABLE_ACTIONS, approval.action_type):
        return verdict(MANUAL_ONLY_REASONS.get(approval.action_type, f"'{approval.action_type}' is not on the auto-approval allowlist"))
    if not check("risk level low or medium", approval.risk_level in {"low", "medium"}, approval.risk_level):
        return verdict(f"Risk level {approval.risk_level} needs a person")
    wording = EXTERNAL_OR_WRITE_WORDS.search(f"{approval.title} {evidence.get('summary', '')} {evidence.get('name', '')}")
    if not check("no copy, export, delete or external wording", wording is None, wording.group(0) if wording else ""):
        return verdict(f"The request mentions '{wording.group(0)}', which may move data or reach an external system")
    requester = db.get(User, approval.requested_by)
    if not check("requester is an active user", requester is not None and requester.active):
        return verdict("The requester is no longer active")
    if approval.action_type == "publish_superset_query":
        from .services.sql_service import _safe_read_only_sql

        sql = _approved_sql(db, project, evidence)
        if not check("SQL is the immutable artifact version", bool(sql) and sql.strip() == str(evidence.get("sql", "")).strip()):
            return verdict("The SQL no longer matches the saved artifact version")
        guard = check_read_only(sql, "postgres")
        if not check("sql_guard: one read-only SELECT", guard.ok and _safe_read_only_sql(sql), guard.reason):
            return verdict(f"SQL is not a safe read-only query: {guard.reason or 'failed the read-only shape check'}")
        flagged, missing = _pii_columns(db, project, sql, guard.relations, list(evidence.get("columns") or []))
        if not check("only catalogued relations", not missing, ", ".join(missing)):
            return verdict(f"PII cannot be ruled out for uncatalogued relations: {', '.join(missing)}")
        if not check("no PII columns referenced or returned", not flagged, ", ".join(flagged)):
            return verdict(f"References PII columns: {', '.join(flagged)}")
    from .routers.approvals import SEPARATE_APPROVER_ACTIONS

    if not check("separation of duties allows a policy approval", not (separation_of_duties() and approval.action_type in SEPARATE_APPROVER_ACTIONS)):
        return verdict("Separation of duties is on: a second person must approve this action")
    return verdict("Read-only SQL over catalogued, non-PII columns; publishing is reversible")


def _record(db: Session, project: Project, approval: Approval, review: dict[str, Any]) -> None:
    previous = (approval.evidence or {}).get("auto_review") or {}
    approval.evidence = {**(approval.evidence or {}), "auto_review": review}
    if previous.get("decision") != review["decision"] or previous.get("reason") != review["reason"]:
        db.add(AuditEvent(project_id=project.id, actor_id=None, event_type=f"approval.auto_review_{review['decision']}", entity_type="approval", entity_id=approval.id, details=review))
        record_audit_event(f"approval.auto_review_{review['decision']}", "approval", approval.id, project_id=project.id, details={"reason": review["reason"]})


def review_approval(db: Session, project: Project, approval: Approval, trigger: str) -> dict[str, Any]:
    """Evaluate one pending approval and approve it when it qualifies. No-op when the project's switch is off."""
    if not auto_approval_enabled(project) or approval.status != "pending":
        return {"approval_id": approval.id, "decision": "skipped", "reason": "Auto-approval is off for this project" if approval.status == "pending" else "Already decided"}
    from fastapi import HTTPException

    from .routers.approvals import apply_approval_decision

    result = evaluate(db, project, approval)
    passed = [item["check"] for item in result["checks"] if item["passed"]]
    review = {
        "decision": "approved" if result["eligible"] else "manual",
        "reason": result["reason"],
        "checks": result["checks"],
        "policy_version": POLICY_VERSION,
        "trigger": trigger,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if not result["eligible"]:
        _record(db, project, approval, review)
        db.commit()
        return {"approval_id": approval.id, **review}
    approval.evidence = {**(approval.evidence or {}), "auto_review": review}
    note = f"Auto-approved by policy: {result['reason']}. Checks passed: {'; '.join(passed)}."
    try:
        apply_approval_decision(db, project, approval, "approved", note, db.get(User, approval.requested_by), auto_policy=review)
    except HTTPException as exc:
        # Side effect failed before commit (e.g. Superset down): leave it pending for a person or a later run.
        db.rollback()
        approval = db.get(Approval, approval.id)
        review = {**review, "decision": "manual", "reason": f"Checks passed but the action failed: {exc.detail}"}
        _record(db, project, approval, review)
        db.commit()
    return {"approval_id": approval.id, **review}


def review_pending(db: Session, project: Project, trigger: str = "manual_run") -> list[dict[str, Any]]:
    pending = db.scalars(select(Approval).where(Approval.project_id == project.id, Approval.status == "pending").order_by(Approval.created_at)).all()
    return [review_approval(db, project, approval, trigger) for approval in pending]
