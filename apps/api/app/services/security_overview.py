"""Security posture scoring over incidents (categories, severities, score, posture)."""
from __future__ import annotations

import json
from datetime import datetime

from ..models import Incident


SECURITY_CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("prompt_injection", "Prompt Injection", ("prompt injection", "jailbreak", "instruction override")),
    ("pii_exposure", "PII Exposure", ("pii", "social security", "ssn", "credit card", "personal data")),
    ("toxic_content", "Toxic Content", ("toxic", "abusive", "hate speech", "harassment")),
]
SECURITY_CATEGORY_LABELS = {key: label for key, label, _ in SECURITY_CATEGORIES}
SECURITY_SEVERITIES = ("critical", "high", "medium", "low")


def _security_bucket_label(value: datetime) -> str:
    return f"{value.strftime('%b')} {value.day}"


def _security_text(incident: Incident) -> str:
    return " ".join(
        part
        for part in (
            incident.title,
            incident.root_cause,
            json.dumps(incident.evidence, separators=(",", ":"), default=str),
            " ".join(incident.remediation or []),
        )
        if part
    ).lower()


def _security_category_from_incident(incident: Incident) -> str | None:
    text = _security_text(incident)
    for key, _, keywords in SECURITY_CATEGORIES:
        if any(keyword in text for keyword in keywords):
            return key
    return None


def _security_score(incidents: list[Incident]) -> int:
    deductions = {"critical": 20, "high": 12, "medium": 7, "low": 3}
    score = 100
    for incident in incidents:
        score -= deductions.get((incident.severity or "").lower(), 5)
    return max(0, min(100, score))


def _security_posture(score: int) -> str:
    if score >= 90:
        return "Good"
    if score >= 75:
        return "Monitor"
    return "At Risk"
