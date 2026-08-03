"""Optional AgentGuard observability for governed model calls.

This module deliberately treats AgentGuard as a non-blocking integration: a
telemetry outage must never prevent a governed workload from completing.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx


LOGGER = logging.getLogger("datapilot.governance.agentguard")
SCORE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agentguard-score")


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _suppress_exporter_noise() -> None:
    """Keep AgentGuard fail-open in local runs without OTLP retry storms in logs."""
    if not _env_flag("AGENTGUARD_SUPPRESS_EXPORT_LOGS", "true"):
        return
    for logger_name in (
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
    ):
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)


def _is_enabled() -> bool:
    return _env_flag("AGENTGUARD_ENABLED")


def include_infra_spans_enabled() -> bool:
    return _env_flag("AGENTGUARD_INCLUDE_INFRA_SPANS")


def governance_event_export_enabled() -> bool:
    configured = os.getenv("AGENTGUARD_EXPORT_GOVERNANCE_EVENTS")
    if configured is not None:
        return _env_flag("AGENTGUARD_EXPORT_GOVERNANCE_EVENTS")
    return include_infra_spans_enabled()


def _vendor(model: str, provider_type: str) -> str:
    if provider_type == "gemini":
        return "google"
    if provider_type == "claude":
        return "anthropic"
    if provider_type:
        return provider_type
    name = (model or "").lower()
    if name.startswith("gemini"):
        return "google"
    if name.startswith("claude"):
        return "anthropic"
    return "openai"


def _record_generation_span(
    *,
    feature: str,
    model: str,
    provider_type: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int | None,
    input_text: str | None,
    output_text: str | None,
    level: str,
) -> bool:
    """Use AgentGuard's configured tracer directly when the SDK lacks content fields."""
    try:
        from opentelemetry.trace import Status, StatusCode
        import agentguard._config as config
        import agentguard._dimensions as dimensions
        import agentguard._tracing as tracing

        current = tracing._ctx.get()
        business_id = current.get("business_id")
        channel = current.get("channel")
        session_id = current.get("session_id")
        user_id = current.get("user_id") or business_id
        tracer = tracing._tracer
        if tracer is None:
            return False

        span = tracer.start_span(feature)
        try:
            tracing._apply_trace_attrs(
                span,
                user_id=user_id,
                session_id=session_id,
                tags=dimensions.call_tags(business_id, channel, feature),
                metadata=dimensions.metadata(
                    business_id,
                    channel,
                    config.settings.app_env,
                    feature=feature,
                    provider_type=provider_type,
                    latency_ms=max(0, latency_ms) if latency_ms is not None else None,
                    duration_ms=max(0, latency_ms) if latency_ms is not None else None,
                ),
            )
            span.set_attribute("langfuse.observation.type", "generation")
            span.set_attribute("gen_ai.system", _vendor(model, provider_type))
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("gen_ai.response.model", model)
            span.set_attribute("langfuse.observation.model.name", model)
            span.set_attribute("gen_ai.usage.input_tokens", max(0, input_tokens))
            span.set_attribute("gen_ai.usage.output_tokens", max(0, output_tokens))
            span.set_attribute("gen_ai.usage.total_tokens", max(0, input_tokens) + max(0, output_tokens))
            if latency_ms is not None:
                span.set_attribute("gen_ai.client.operation.duration_ms", max(0, latency_ms))
            if input_text:
                span.set_attribute("input.value", input_text)
                span.set_attribute("input.mime_type", "application/json")
                span.set_attribute("gen_ai.prompt", input_text)
                span.set_attribute("langfuse.observation.input", input_text)
            if output_text:
                span.set_attribute("output.value", output_text)
                span.set_attribute("output.mime_type", "text/plain")
                span.set_attribute("gen_ai.completion", output_text)
                span.set_attribute("langfuse.observation.output", output_text)
            span.set_status(Status(StatusCode.ERROR) if level == "error" else Status(StatusCode.OK))
        finally:
            span.end()
        tracing.flush()
        return True
    except Exception:
        return False


def initialize_agentguard() -> bool:
    """Initialize AgentGuard once per process when explicitly configured."""
    if not _is_enabled():
        LOGGER.info("AgentGuard telemetry is disabled by configuration.")
        return False
    try:
        import agentguard

        _suppress_exporter_noise()
        agentguard.init(
            service_name=os.getenv("AGENTGUARD_SERVICE_NAME", "datapilot-agent-os"),
            environment=os.getenv("APP_ENV", "development"),
            mode=os.getenv("AGENTGUARD_MODE", "auto"),
            drop_infra_spans=not include_infra_spans_enabled(),
        )
        enabled = bool(agentguard.is_enabled())
        if enabled:
            LOGGER.info("AgentGuard telemetry initialized successfully.")
        else:
            LOGGER.warning("AgentGuard telemetry did not initialize; verify endpoint and credentials.")
        return enabled
    except Exception as exc:
        # Governance telemetry is intentionally fail-open; local policy and
        # application audit controls remain available if the exporter is down.
        LOGGER.warning("AgentGuard initialization failed: %s", exc)
        return False


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
    """Export a generation record with optional redacted input/output content."""
    if not _is_enabled():
        return
    try:
        import agentguard

        if not agentguard.is_enabled():
            return
        with agentguard.context(
            business_id=tenant_id or business_id or "datapilot",
            channel="api",
            session_id=session_id,
            user_id=user_id,
        ):
            if (input_text or output_text) and _record_generation_span(
                feature=feature,
                model=model,
                provider_type=provider_type,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                input_text=input_text,
                output_text=output_text,
                level=level,
            ):
                return
            agentguard.record_generation(
                feature=feature,
                model=model,
                input_tokens=max(0, input_tokens),
                output_tokens=max(0, output_tokens),
                level=level,
                provider_type=provider_type,
                latency_ms=max(0, latency_ms) if latency_ms is not None else None,
                duration_ms=max(0, latency_ms) if latency_ms is not None else None,
                input=input_text,
                output=output_text,
                input_value=input_text,
                output_value=output_text,
            )
    except Exception as exc:
        # Never allow the observability integration to alter model behavior.
        LOGGER.warning("AgentGuard generation export failed for feature '%s': %s", feature, exc)
        return


def record_agentguard_event(
    *,
    event_type: str,
    name: str,
    outcome: str,
    business_id: str | None = None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    feature: str | None = None,
    risk_level: str | None = None,
    metadata: dict[str, str | int | float | bool] | None = None,
) -> None:
    """Export a non-LLM custom span for the generic governance contract."""
    if not _is_enabled() or not governance_event_export_enabled():
        return
    try:
        import agentguard

        if not agentguard.is_enabled():
            return
        attributes = {"event_type": event_type, "outcome": outcome, **(metadata or {})}
        if business_id:
            attributes["project_id"] = business_id
        if tenant_id:
            attributes["tenant"] = tenant_id
            attributes["tenantId"] = tenant_id
        if feature:
            # `track` already receives its first positional value as the
            # AgentGuard feature. Passing another `feature` keyword raises
            # "multiple values for argument 'feature'" and drops the event.
            attributes["datapilot.feature"] = feature
        if risk_level:
            attributes["risk_level"] = risk_level
        with agentguard.context(
            business_id=tenant_id or business_id or "datapilot",
            channel="governance",
            session_id=session_id,
            user_id=user_id,
        ):
            with agentguard.track(name, **attributes):
                pass
    except Exception as exc:
        LOGGER.warning("AgentGuard event export failed for '%s': %s", name, exc)
        return


def record_agentguard_score(
    *,
    score_id: str,
    name: str,
    value: float,
    data_type: str,
    session_id: str,
    comment: str | None = None,
) -> None:
    """Submit a native AgentGuard score asynchronously and fail open on errors."""
    if not _is_enabled():
        return
    base_url = os.getenv("AGENTGUARD_BASE_URL", "").rstrip("/")
    public_key = os.getenv("AGENTGUARD_PUBLIC_KEY", "")
    secret_key = os.getenv("AGENTGUARD_SECRET_KEY", "")
    if not (base_url and public_key and secret_key):
        return
    payload: dict[str, Any] = {
        "id": score_id,
        "sessionId": session_id,
        "name": name,
        "value": value,
        "dataType": data_type,
    }
    if comment:
        payload["comment"] = comment

    def submit() -> None:
        try:
            with httpx.Client(timeout=3.0, follow_redirects=False) as client:
                response = client.post(
                    f"{base_url}/api/public/scores",
                    json=payload,
                    auth=(public_key, secret_key),
                )
                response.raise_for_status()
        except Exception as exc:
            LOGGER.warning("AgentGuard score export failed for '%s': %s", name, exc)

    SCORE_EXECUTOR.submit(submit)
