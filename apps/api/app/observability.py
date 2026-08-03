from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


request_id: ContextVar[str] = ContextVar("datapilot_request_id", default="")
_tracer = None
_configured = False


def initialize_observability() -> dict[str, str | bool]:
    """Configure OTLP only when explicitly enabled; local startup never depends on a collector."""
    global _tracer, _configured
    enabled = os.getenv("OTEL_ENABLED", "false").lower() in {"1", "true", "yes"}
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not enabled or not endpoint:
        return {"enabled": False, "configured": False, "reason": "OTEL_ENABLED and OTEL_EXPORTER_OTLP_ENDPOINT are required"}
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "datapilot-api")}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("datapilot.control-plane")
        _configured = True
        return {"enabled": True, "configured": True, "endpoint": endpoint}
    except Exception as exc:
        logging.getLogger("datapilot.observability").warning("OTLP setup skipped: %s", exc)
        return {"enabled": True, "configured": False, "reason": str(exc)[:300]}


@contextmanager
def span(name: str, **attributes: str | int) -> Iterator[None]:
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name) as active_span:
        for key, value in attributes.items():
            active_span.set_attribute(key, value)
        yield


def emit(event: str, **fields: str | int | bool) -> None:
    payload = {"event": event, "request_id": request_id.get() or None, **fields}
    logging.getLogger("datapilot.events").info(json.dumps(payload, default=str, separators=(",", ":")))


def status() -> dict[str, str | bool]:
    return {
        "enabled": os.getenv("OTEL_ENABLED", "false").lower() in {"1", "true", "yes"},
        "configured": _configured,
        "service_name": os.getenv("OTEL_SERVICE_NAME", "datapilot-api"),
        "endpoint_configured": bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()),
    }


def elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
