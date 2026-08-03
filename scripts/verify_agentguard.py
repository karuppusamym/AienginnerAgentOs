from __future__ import annotations

import json
import os
import time
from typing import Any


def _masked(value: str | None) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _env_summary() -> dict[str, str]:
    return {
        "GOVERNANCE_ENABLED": os.getenv("GOVERNANCE_ENABLED", ""),
        "GOVERNANCE_PROVIDERS": os.getenv("GOVERNANCE_PROVIDERS", ""),
        "AGENTGUARD_ENABLED": os.getenv("AGENTGUARD_ENABLED", ""),
        "AGENTGUARD_MODE": os.getenv("AGENTGUARD_MODE", ""),
        "AGENTGUARD_BASE_URL": os.getenv("AGENTGUARD_BASE_URL", ""),
        "AGENTGUARD_PUBLIC_KEY": _masked(os.getenv("AGENTGUARD_PUBLIC_KEY")),
        "AGENTGUARD_SECRET_KEY": _masked(os.getenv("AGENTGUARD_SECRET_KEY")),
        "AGENTGUARD_INCLUDE_INFRA_SPANS": os.getenv("AGENTGUARD_INCLUDE_INFRA_SPANS", ""),
    }


def main() -> int:
    import agentguard

    from app.governance import initialize_governance, record_governance_event, record_model_generation

    print("AgentGuard manual verification")
    print(json.dumps({"env": _env_summary()}, separators=(",", ":")))
    print(json.dumps({"before_init_enabled": bool(agentguard.is_enabled())}, separators=(",", ":")))

    initialized = bool(initialize_governance())
    print(json.dumps({"initialize_governance": initialized, "after_init_enabled": bool(agentguard.is_enabled())}, separators=(",", ":")))

    started = time.time()
    record_governance_event(
        "verification",
        "manual_agentguard_event",
        "ok",
        project_id="datapilot",
        user_id="codex",
        session_id=f"manual-{int(started)}",
        source="manual-script",
    )
    record_model_generation(
        feature="manual_agentguard_generation",
        model="manual-test-model",
        provider_type="manual",
        input_tokens=11,
        output_tokens=7,
        business_id="datapilot",
        session_id=f"manual-{int(started)}",
        user_id="codex",
    )
    print(json.dumps({"emitted": ["verification", "model_generation"], "flush_wait_seconds": 8}, separators=(",", ":")))
    time.sleep(8)
    print(json.dumps({"status": "completed"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
