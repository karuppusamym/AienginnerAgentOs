from __future__ import annotations

import os
from typing import Any

import httpx


def _settings() -> tuple[str, dict[str, str]]:
    base_url = os.getenv("DATAPILOT_URL", "http://localhost:8000").rstrip("/")
    token = os.getenv("DATAPILOT_EXTERNAL_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DATAPILOT_EXTERNAL_TOKEN is required")
    return base_url, {"Authorization": f"Bearer {token}"}


def search_registered_tools(query: str, line_of_business: str = "") -> dict[str, Any]:
    """Search granted governed database tools by description, purpose, source, LOB, owner, or tag."""
    base_url, headers = _settings()
    with httpx.Client(base_url=base_url, headers=headers, timeout=20) as client:
        response = client.get(
            "/external/v1/query-tools",
            params={"q": query, "line_of_business": line_of_business},
        )
        response.raise_for_status()
        return response.json()


def invoke_registered_tool(tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Invoke one granted read-only database tool with parameters that match its published input schema."""
    base_url, headers = _settings()
    with httpx.Client(base_url=base_url, headers=headers, timeout=130) as client:
        response = client.post(
            f"/external/v1/query-tools/{tool_name}/invoke",
            json={"parameters": parameters},
        )
        response.raise_for_status()
        return response.json()
