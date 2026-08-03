"""Provider-neutral, metadata-only governance telemetry contract.

The application emits stable event envelopes and can fan them out to one or
more adapters. Local authorization, approvals, and audit records remain the
enforcement controls; adapters are intentionally fail-open observers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import BoundedSemaphore
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx


SENSITIVE_METADATA_MARKERS = {
    "argument", "authorization", "content", "credential", "key", "note",
    "parameter", "password", "prompt", "query", "response", "result",
    "secret", "sql", "token",
}
try:
    MAX_GENERATION_CONTENT_CHARS = max(1, int(os.getenv("GOVERNANCE_GENERATION_CONTENT_MAX_CHARS", "6000")))
except ValueError:
    MAX_GENERATION_CONTENT_CHARS = 6000
SECRET_PATTERN = re.compile(
    r"(?i)\b((?:api[_-]?key|authorization|bearer|password|secret|token)\s*[:=]\s*)([^\s,;\"']+)"
)
WEBHOOK_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="governance-webhook")
WEBHOOK_SLOTS = BoundedSemaphore(value=500)
LOGGER = logging.getLogger("datapilot.governance")


@dataclass(frozen=True)
class GovernanceEvent:
    event_type: str
    name: str
    outcome: str
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    project_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    feature: str | None = None
    risk_level: str | None = None
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class GovernanceGeneration:
    feature: str
    model: str
    provider_type: str
    input_tokens: int
    output_tokens: int
    latency_ms: int | None = None
    input_text: str | None = None
    output_text: str | None = None
    level: str = "ok"
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    project_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class GovernanceScore:
    score_id: str
    name: str
    value: float
    data_type: str
    session_id: str
    comment: str | None = None


class GovernanceAdapter(Protocol):
    def initialize(self) -> bool: ...

    def record_event(self, event: GovernanceEvent) -> None: ...

    def record_generation(self, generation: GovernanceGeneration) -> None: ...

    def record_score(self, score: GovernanceScore) -> None: ...


class AgentGuardAdapter:
    """Adapter for AgentGuard custom spans and generation records."""

    def initialize(self) -> bool:
        from .agentguard_runtime import initialize_agentguard

        return initialize_agentguard()

    def record_event(self, event: GovernanceEvent) -> None:
        from .agentguard_runtime import record_agentguard_event

        record_agentguard_event(
            event_type=event.event_type,
            name=event.name,
            outcome=event.outcome,
            business_id=event.project_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            session_id=event.session_id,
            feature=event.feature,
            risk_level=event.risk_level,
            metadata=event.metadata,
        )

    def record_generation(self, generation: GovernanceGeneration) -> None:
        from .agentguard_runtime import record_model_generation

        record_model_generation(
            feature=generation.feature,
            model=generation.model,
            provider_type=generation.provider_type,
            input_tokens=generation.input_tokens,
            output_tokens=generation.output_tokens,
            latency_ms=generation.latency_ms,
            input_text=generation.input_text,
            output_text=generation.output_text,
            level=generation.level,
            business_id=generation.project_id,
            tenant_id=generation.tenant_id,
            session_id=generation.session_id,
            user_id=generation.user_id,
        )

    def record_score(self, score: GovernanceScore) -> None:
        from .agentguard_runtime import record_agentguard_score

        record_agentguard_score(
            score_id=score.score_id,
            name=score.name,
            value=score.value,
            data_type=score.data_type,
            session_id=score.session_id,
            comment=score.comment,
        )


def _configured_headers(variable: str) -> dict[str, str]:
    raw = os.getenv(variable, "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if isinstance(key, str) and isinstance(item, (str, int, float))}


class QuietSpanExporter:
    """Prevent an unavailable telemetry endpoint from logging application errors."""

    def __init__(self, exporter: Any) -> None:
        self._exporter = exporter

    def export(self, spans: Any) -> Any:
        try:
            return self._exporter.export(spans)
        except Exception:
            from opentelemetry.sdk.trace.export import SpanExportResult

            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        try:
            self._exporter.shutdown()
        except Exception:
            return

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            return bool(self._exporter.force_flush(timeout_millis))
        except Exception:
            return False


class OtlpAdapter:
    """Standards-based OTLP/HTTP exporter for Phoenix, Langfuse, and collectors."""

    def __init__(self) -> None:
        self._provider: Any | None = None
        self._tracer: Any | None = None

    def initialize(self) -> bool:
        if self._tracer is not None:
            return True
        endpoint = os.getenv("GOVERNANCE_OTLP_ENDPOINT", "").strip()
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(
                resource=Resource.create({
                    "service.name": os.getenv("GOVERNANCE_SERVICE_NAME", "datapilot-agent-os"),
                    "deployment.environment": os.getenv("APP_ENV", "development"),
                })
            )
            exporter = OTLPSpanExporter(endpoint=endpoint, headers=_configured_headers("GOVERNANCE_OTLP_HEADERS_JSON"))
            provider.add_span_processor(BatchSpanProcessor(QuietSpanExporter(exporter)))
            self._provider = provider
            self._tracer = provider.get_tracer("datapilot.governance")
            return True
        except Exception:
            return False

    def _record(self, name: str, attributes: dict[str, str | int | float | bool], failed: bool) -> None:
        if self._tracer is None:
            return
        try:
            from opentelemetry.trace import Status, StatusCode

            with self._tracer.start_as_current_span(name) as span:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
                span.set_status(Status(StatusCode.ERROR) if failed else Status(StatusCode.OK))
        except Exception:
            return

    def record_event(self, event: GovernanceEvent) -> None:
        attributes: dict[str, str | int | float | bool] = {
            "governance.event.type": event.event_type,
            "governance.event.outcome": event.outcome,
            "governance.event.occurred_at": event.occurred_at,
            **{f"governance.metadata.{key}": value for key, value in event.metadata.items()},
        }
        for key, value in (("datapilot.project.id", event.project_id), ("tenant.id", event.tenant_id), ("governance.tenant.id", event.tenant_id), ("enduser.id", event.user_id), ("session.id", event.session_id), ("governance.feature", event.feature), ("governance.risk.level", event.risk_level)):
            if value:
                attributes[key] = value
        self._record(event.name, attributes, event.outcome in {"failed", "error"})

    def record_generation(self, generation: GovernanceGeneration) -> None:
        attributes: dict[str, str | int | float | bool] = {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": generation.provider_type,
            "gen_ai.request.model": generation.model,
            "gen_ai.response.model": generation.model,
            "gen_ai.usage.input_tokens": generation.input_tokens,
            "gen_ai.usage.output_tokens": generation.output_tokens,
            "governance.feature": generation.feature,
            "governance.event.occurred_at": generation.occurred_at,
        }
        if generation.latency_ms is not None:
            attributes["gen_ai.client.operation.duration_ms"] = generation.latency_ms
        if generation.input_text:
            attributes["input.value"] = generation.input_text
            attributes["input.mime_type"] = "application/json"
            attributes["gen_ai.prompt"] = generation.input_text
        if generation.output_text:
            attributes["output.value"] = generation.output_text
            attributes["output.mime_type"] = "text/plain"
            attributes["gen_ai.completion"] = generation.output_text
        for key, value in (("datapilot.project.id", generation.project_id), ("tenant.id", generation.tenant_id), ("governance.tenant.id", generation.tenant_id), ("enduser.id", generation.user_id), ("session.id", generation.session_id)):
            if value:
                attributes[key] = value
        self._record(generation.feature, attributes, generation.level in {"failed", "error"})

    def record_score(self, score: GovernanceScore) -> None:
        attributes: dict[str, str | int | float | bool] = {
            "langfuse.score.name": score.name,
            "langfuse.score.value": score.value,
            "langfuse.score.data_type": score.data_type,
            "session.id": score.session_id,
        }
        if score.comment:
            attributes["langfuse.score.comment"] = score.comment
        self._record(f"score.{score.name}", attributes, False)


class WebhookAdapter:
    """Generic HTTPS JSON adapter for a vendor or an internal governance gateway."""

    def __init__(self) -> None:
        self._url = ""
        self._headers: dict[str, str] = {}
        self._signing_secret = ""

    def initialize(self) -> bool:
        url = os.getenv("GOVERNANCE_WEBHOOK_URL", "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        self._url = url
        self._headers = _configured_headers("GOVERNANCE_WEBHOOK_HEADERS_JSON")
        self._signing_secret = os.getenv("GOVERNANCE_WEBHOOK_SIGNING_SECRET", "")
        return True

    def _submit(self, kind: str, payload: dict[str, Any]) -> None:
        if not self._url or not WEBHOOK_SLOTS.acquire(blocking=False):
            return

        def send() -> None:
            try:
                body = json.dumps({"schema_version": "1.0", "kind": kind, "service": os.getenv("GOVERNANCE_SERVICE_NAME", "datapilot-agent-os"), "payload": payload}, separators=(",", ":"))
                headers = {"content-type": "application/json", "user-agent": "datapilot-governance/1.0", **self._headers}
                if self._signing_secret:
                    headers["x-governance-signature-sha256"] = hmac.new(self._signing_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
                with httpx.Client(timeout=3.0, follow_redirects=False) as client:
                    client.post(self._url, content=body, headers=headers).raise_for_status()
            except Exception:
                pass
            finally:
                WEBHOOK_SLOTS.release()

        WEBHOOK_EXECUTOR.submit(send)

    def record_event(self, event: GovernanceEvent) -> None:
        self._submit("event", asdict(event))

    def record_generation(self, generation: GovernanceGeneration) -> None:
        self._submit("generation", asdict(generation))

    def record_score(self, score: GovernanceScore) -> None:
        self._submit("score", asdict(score))


def _enabled() -> bool:
    value = os.getenv("GOVERNANCE_ENABLED")
    if value is None:
        value = os.getenv("AGENTGUARD_ENABLED", "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _provider_names() -> list[str]:
    configured = os.getenv("GOVERNANCE_PROVIDERS") or os.getenv("GOVERNANCE_PROVIDER", "agentguard")
    return list(dict.fromkeys(name.strip().lower() for name in configured.split(",") if name.strip() and name.strip().lower() != "none"))


_ADAPTERS: dict[str, GovernanceAdapter] = {}


def _adapter_items() -> list[tuple[str, GovernanceAdapter]]:
    if not _enabled():
        return []
    factories: dict[str, type[GovernanceAdapter]] = {"agentguard": AgentGuardAdapter, "otlp": OtlpAdapter, "webhook": WebhookAdapter}
    adapters: list[tuple[str, GovernanceAdapter]] = []
    for name in _provider_names():
        factory = factories.get(name)
        if factory is None:
            LOGGER.warning("Unknown governance provider '%s' was ignored.", name)
            continue
        adapter = _ADAPTERS.setdefault(name, factory())
        adapters.append((name, adapter))
    return adapters


def _adapters() -> list[GovernanceAdapter]:
    return [adapter for _, adapter in _adapter_items()]


def initialize_governance() -> bool:
    """Initialize all configured adapters. Invalid/unavailable adapters are skipped."""
    if not _enabled():
        LOGGER.info("Governance telemetry is disabled by configuration.")
        return False
    initialized = False
    successful: list[str] = []
    failed: list[str] = []
    for name, adapter in _adapter_items():
        try:
            if adapter.initialize():
                initialized = True
                successful.append(name)
            else:
                failed.append(name)
        except Exception as exc:
            LOGGER.warning("Governance adapter '%s' failed during initialization: %s", name, exc)
            failed.append(name)
            continue
    if successful:
        LOGGER.info("Governance telemetry initialized for provider(s): %s", ", ".join(successful))
    if failed:
        LOGGER.warning("Governance telemetry did not initialize for provider(s): %s", ", ".join(failed))
    return initialized


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    safe: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        normalized_key = str(key).lower()
        if any(marker in normalized_key for marker in SENSITIVE_METADATA_MARKERS):
            continue
        if isinstance(value, (str, int, float, bool)):
            safe[str(key)[:80]] = value if not isinstance(value, str) else value[:500]
    return safe


def _tenant_id(tenant_id: str | None, project_id: str | None) -> str | None:
    configured = os.getenv("GOVERNANCE_TENANT_ID") or os.getenv("AGENTGUARD_TENANT_ID")
    return tenant_id or configured or project_id


def _capture_generation_content_enabled() -> bool:
    return os.getenv("AGENTGUARD_CAPTURE_CONTENT", "false").strip().lower() in {"1", "true", "yes", "on"}


def _redact_generation_text(value: str | None) -> str | None:
    if not value or not _capture_generation_content_enabled():
        return None
    text = SECRET_PATTERN.sub(r"\1[REDACTED]", value)
    for key, secret in os.environ.items():
        normalized_key = key.lower()
        if not any(marker in normalized_key for marker in SENSITIVE_METADATA_MARKERS):
            continue
        if len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    if len(text) > MAX_GENERATION_CONTENT_CHARS:
        return f"{text[:MAX_GENERATION_CONTENT_CHARS]}...[truncated]"
    return text


def _dispatch(method: str, value: GovernanceEvent | GovernanceGeneration) -> None:
    for adapter in _adapters():
        try:
            getattr(adapter, method)(value)
        except Exception:
            continue


def record_governance_event(
    event_type: str,
    name: str,
    outcome: str,
    *,
    project_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    feature: str | None = None,
    risk_level: str | None = None,
    **metadata: Any,
) -> None:
    """Emit a sanitized, fail-open governance event to every configured adapter."""
    _dispatch("record_event", GovernanceEvent(
        event_type=event_type[:80], name=name[:160], outcome=outcome[:40],
        project_id=project_id, tenant_id=_tenant_id(tenant_id, project_id), user_id=user_id, session_id=session_id,
        feature=feature[:160] if feature else name[:160],
        risk_level=risk_level[:40] if risk_level else None, metadata=_safe_metadata(metadata),
    ))


def record_audit_event(
    event_type: str,
    entity_type: str,
    entity_id: str | None,
    *,
    project_id: str | None = None,
    user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Mirror a durable audit entry without allowing detail keys to override its envelope."""
    telemetry_details = {f"detail.{key}": value for key, value in (details or {}).items()}
    record_governance_event(
        "audit_event",
        event_type,
        "recorded",
        project_id=project_id,
        user_id=user_id,
        session_id=entity_id,
        entity_type=entity_type,
        entity_id=entity_id or "",
        **telemetry_details,
    )


def record_model_generation(
    *,
    feature: str,
    model: str,
    provider_type: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int | None = None,
    input_text: str | None = None,
    output_text: str | None = None,
    level: str = "ok",
    business_id: str | None = None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Emit a fail-open LLM generation record to every configured adapter."""
    _dispatch("record_generation", GovernanceGeneration(
        feature=feature[:160], model=model[:200], provider_type=provider_type[:80],
        input_tokens=max(0, input_tokens), output_tokens=max(0, output_tokens),
        latency_ms=max(0, latency_ms) if latency_ms is not None else None,
        input_text=_redact_generation_text(input_text),
        output_text=_redact_generation_text(output_text),
        level=level[:40], project_id=business_id, tenant_id=_tenant_id(tenant_id, business_id),
        session_id=session_id, user_id=user_id,
    ))


def record_governance_score(
    *,
    score_id: str,
    name: str,
    value: float | bool,
    session_id: str | None,
    data_type: str = "NUMERIC",
    comment: str | None = None,
) -> None:
    """Export a normalized, session-linked quality score without application content."""
    if not score_id or not session_id:
        return
    normalized_type = data_type.upper()
    if normalized_type not in {"NUMERIC", "BOOLEAN"}:
        return
    normalized_value = float(value)
    if normalized_type == "BOOLEAN":
        normalized_value = 1.0 if normalized_value else 0.0
    _dispatch("record_score", GovernanceScore(
        score_id=score_id[:80],
        name=name[:100],
        value=normalized_value,
        data_type=normalized_type,
        session_id=session_id[:80],
        comment=comment[:500] if comment else None,
    ))
