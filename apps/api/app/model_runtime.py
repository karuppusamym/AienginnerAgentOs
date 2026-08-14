from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass

import httpx

from .governance import record_model_generation
from .models import ModelProvider


@dataclass
class ProviderTestResult:
    status: str
    message: str
    latency_ms: int | None = None
    error: str | None = None


@dataclass
class ProviderGenerationResult:
    content: str
    latency_ms: int


def resolve_secret(reference: str | None) -> str | None:
    if not reference:
        return None
    if reference.startswith("env:"):
        return os.getenv(reference[4:])
    return None


def _message_text(payload: dict) -> str:
    if payload.get("choices"):
        return str(payload["choices"][0].get("message", {}).get("content", ""))
    if payload.get("content"):
        content = payload["content"]
        if isinstance(content, list) and content:
            return str(content[0].get("text", ""))
    candidates = payload.get("candidates") or []
    if candidates:
        parts = candidates[0].get("content", {}).get("parts") or []
        # Reasoning-capable Gemini models can emit a hidden "thought" part
        # ahead of the real answer. Skip those so a thinking trace never gets
        # mistaken for the structured output the caller actually asked for.
        answer_parts = [part for part in parts if not part.get("thought")]
        if answer_parts:
            return str(answer_parts[0].get("text", ""))
        if parts:
            return str(parts[0].get("text", ""))
    return ""


def _usage_tokens(payload: dict[str, object], fallback_input: int, fallback_output: int) -> tuple[int, int]:
    """Read provider usage where available, with a conservative fallback."""
    usage = payload.get("usage") or payload.get("usageMetadata") or payload.get("usage_metadata") or {}
    if not isinstance(usage, dict):
        return fallback_input, fallback_output
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("promptTokenCount", fallback_input)))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens", usage.get("candidatesTokenCount", fallback_output)))
    try:
        return max(0, int(input_tokens)), max(0, int(output_tokens))
    except (TypeError, ValueError):
        return fallback_input, fallback_output


def _generation_input_text(messages: list[dict[str, str]]) -> str:
    return json.dumps(messages, ensure_ascii=False, separators=(",", ":"))


def _openai_chat_payload(model: str, messages: list[dict[str, str]], max_tokens: int) -> dict[str, object]:
    """Build a Chat Completions payload compatible with legacy and GPT-5 models."""
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
    }
    if model.startswith("gpt-5"):
        # GPT-5 models use the newer completion-token parameter and do not
        # accept an explicit temperature setting.
        payload["max_completion_tokens"] = max_tokens
    else:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = 0
    return payload


def generate_text(
    provider: ModelProvider,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1200,
    governance_feature: str = "model_generation",
    governance_business_id: str | None = None,
    governance_session_id: str | None = None,
    governance_user_id: str | None = None,
) -> ProviderGenerationResult:
    if provider.provider_type == "local_mock":
        return ProviderGenerationResult(content="", latency_ms=1)
    secret = resolve_secret(provider.secret_reference)
    if not secret:
        raise ValueError("The selected model provider secret is unavailable")

    started = time.perf_counter()
    estimated_input = max(1, len(system_prompt + user_prompt) // 4)
    input_text = _generation_input_text([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])
    try:
        with httpx.Client(timeout=45.0) as client:
            if provider.provider_type == "gemini":
                base_url = (provider.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
                response = client.post(
                    f"{base_url}/models/{provider.default_model}:generateContent",
                    headers={"x-goog-api-key": secret},
                    json={
                        "systemInstruction": {"parts": [{"text": system_prompt}]},
                        "contents": [{"parts": [{"text": user_prompt}]}],
                        "generationConfig": {
                            "maxOutputTokens": max_tokens,
                            "temperature": 0,
                            # Structured/governed calls need the visible answer, not a
                            # chain-of-thought trace. Without this, reasoning-capable
                            # Gemini models can spend the whole maxOutputTokens budget
                            # on hidden "thinking" tokens and return an empty answer
                            # part, which then fails downstream JSON parsing.
                            "thinkingConfig": {"thinkingBudget": 0},
                        },
                    },
                )
            elif provider.provider_type == "claude":
                base_url = (provider.base_url or "https://api.anthropic.com/v1").rstrip("/")
                response = client.post(
                    f"{base_url}/messages",
                    headers={"x-api-key": secret, "anthropic-version": "2023-06-01"},
                    json={
                        "model": provider.default_model,
                        "max_tokens": max_tokens,
                        "temperature": 0,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
            else:
                default_url = "https://api.openai.com/v1" if provider.provider_type == "openai" else ""
                base_url = (provider.base_url or default_url).rstrip("/")
                if not base_url:
                    raise ValueError("The selected provider requires a base URL")
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {secret}"},
                    json=_openai_chat_payload(
                        provider.default_model,
                        [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        max_tokens,
                    ),
                )
            response.raise_for_status()
            payload = response.json()
            content = _message_text(payload).strip()
        if not content:
            raise ValueError("The selected model provider returned an empty response")
        input_tokens, output_tokens = _usage_tokens(payload, estimated_input, max(1, len(content) // 4))
        latency_ms = int((time.perf_counter() - started) * 1000)
        record_model_generation(
            feature=governance_feature,
            model=provider.default_model,
            provider_type=provider.provider_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            input_text=input_text,
            output_text=content,
            business_id=governance_business_id,
            session_id=governance_session_id,
            user_id=governance_user_id,
        )
    except Exception as exc:
        record_model_generation(
            feature=governance_feature,
            model=provider.default_model,
            provider_type=provider.provider_type,
            input_tokens=estimated_input,
            output_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_text=input_text,
            output_text=f"error: {type(exc).__name__}",
            level="error",
            business_id=governance_business_id,
            session_id=governance_session_id,
            user_id=governance_user_id,
        )
        raise
    return ProviderGenerationResult(
        content=content,
        latency_ms=latency_ms,
    )


def test_provider(
    provider: ModelProvider,
    *,
    governance_business_id: str | None = None,
    governance_session_id: str | None = None,
    governance_user_id: str | None = None,
) -> ProviderTestResult:
    telemetry_context = {
        key: value
        for key, value in {
            "business_id": governance_business_id,
            "session_id": governance_session_id,
            "user_id": governance_user_id,
        }.items()
        if value is not None
    }
    if provider.provider_type == "local_mock":
        record_model_generation(
            feature="provider_test",
            model=provider.default_model,
            provider_type=provider.provider_type,
            input_tokens=4,
            output_tokens=4,
            latency_ms=1,
            input_text=_generation_input_text([{"role": "user", "content": "Reply with OK only."}]),
            output_text="OK",
            **telemetry_context,
        )
        return ProviderTestResult(
            status="healthy",
            message="Local deterministic provider returned a governed test response",
            latency_ms=1,
        )
    secret = resolve_secret(provider.secret_reference)
    if not provider.secret_reference:
        return ProviderTestResult("configuration_required", "Add an environment secret reference before testing")
    if not secret:
        return ProviderTestResult(
            "secret_unavailable",
            f"The environment variable referenced by {provider.secret_reference} is not available",
        )

    started = time.perf_counter()
    try:
        with httpx.Client(timeout=20.0) as client:
            if provider.provider_type == "gemini":
                base_url = (provider.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
                response = client.post(
                    f"{base_url}/models/{provider.default_model}:generateContent",
                    headers={"x-goog-api-key": secret},
                    json={
                        "contents": [{"parts": [{"text": "Reply with OK only."}]}],
                        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
                    },
                )
            elif provider.provider_type == "claude":
                base_url = (provider.base_url or "https://api.anthropic.com/v1").rstrip("/")
                response = client.post(
                    f"{base_url}/messages",
                    headers={"x-api-key": secret, "anthropic-version": "2023-06-01"},
                    json={
                        "model": provider.default_model,
                        "max_tokens": 8,
                        "messages": [{"role": "user", "content": "Reply with OK only."}],
                    },
                )
            else:
                default_url = "https://api.openai.com/v1" if provider.provider_type == "openai" else ""
                base_url = (provider.base_url or default_url).rstrip("/")
                if not base_url:
                    return ProviderTestResult("configuration_required", "Add the provider base URL")
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {secret}"},
                    json=_openai_chat_payload(
                        provider.default_model,
                        [{"role": "user", "content": "Reply with OK only."}],
                        8,
                    ),
                )
            response.raise_for_status()
            answer = _message_text(response.json()).strip()
        latency_ms = int((time.perf_counter() - started) * 1000)
        record_model_generation(
            feature="provider_test",
            model=provider.default_model,
            provider_type=provider.provider_type,
            input_tokens=4,
            output_tokens=max(1, len(answer) // 4),
            latency_ms=latency_ms,
            input_text=_generation_input_text([{"role": "user", "content": "Reply with OK only."}]),
            output_text=answer,
            **telemetry_context,
        )
        return ProviderTestResult(
            "healthy",
            f"Provider responded successfully{f': {answer[:40]}' if answer else ''}",
            latency_ms,
        )
    except (httpx.HTTPError, ValueError) as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        record_model_generation(
            feature="provider_test",
            model=provider.default_model,
            provider_type=provider.provider_type,
            input_tokens=4,
            output_tokens=0,
            latency_ms=latency_ms,
            input_text=_generation_input_text([{"role": "user", "content": "Reply with OK only."}]),
            output_text=f"error: {type(exc).__name__}",
            level="error",
            **telemetry_context,
        )
        return ProviderTestResult("failed", "Provider invocation failed", latency_ms, str(exc)[:1000])
