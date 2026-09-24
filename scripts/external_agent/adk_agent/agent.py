"""Google ADK agent whose only tools come from DataPilot's MCP gateway.

The agent has no tool code of its own: ``McpToolset`` connects to DataPilot's
``/mcp`` endpoint (streamable HTTP, bearer client token), runs initialize +
tools/list, and exposes every published tool granted to the client as an ADK
tool. Gemini decides which to call; DataPilot validates, executes read-only SQL,
masks PII and audits each call.

Works with the ADK CLI (``adk run adk_agent`` / ``adk web`` from
scripts/external_agent) and with run_adk.py, which prints each step.
"""
from __future__ import annotations

import os
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

HERE = Path(__file__).resolve().parent


def _load_settings() -> None:
    """Environment first, then ../.client.env (client token), then the closest repo .env (Gemini key)."""
    files = [HERE.parent / ".client.env"]
    files += [parent / ".env" for parent in HERE.parents if (parent / ".env").is_file()][:1]
    for path in files:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip().startswith(("DATAPILOT_", "GEMINI_", "GOOGLE_", "ADK_")):  # only what this agent needs
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    # google-genai reads GEMINI_API_KEY (or GOOGLE_API_KEY); use the Gemini API, not Vertex.
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")


_load_settings()

DATAPILOT_API = os.getenv("DATAPILOT_API", "http://localhost:8000").rstrip("/")
if not os.getenv("DATAPILOT_CLIENT_TOKEN"):
    raise RuntimeError("DATAPILOT_CLIENT_TOKEN missing: run scripts/external_agent/setup_demo_gateway.py first")

datapilot_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=f"{DATAPILOT_API}/mcp",
        headers={"Authorization": f"Bearer {os.environ['DATAPILOT_CLIENT_TOKEN']}"},
        timeout=30,
    ),
)

INSTRUCTION = """You are an external analytics agent. Your ONLY source of data is the DataPilot tools you have
(governed, read-only query tools discovered over MCP). Never guess or invent numbers.

To answer:
1. Pick the tool(s) whose description matches the question; pass arguments exactly as their schema requires.
2. Answer in 2-4 sentences. For every figure, name the tool in [brackets] and say how it was derived
   (a cell, or a sum/count over named rows). Keep masked values masked.
3. QA/QC: before finishing, verify the key figure with a DIFFERENTLY SHAPED tool when one exists
   (an aggregate tool -> re-add the detail rows of the matching detail tool, or the reverse).
   End with one line: "QC: PASS - <figure> matched <how>" or "QC: FAIL - <expected> vs <found>",
   or "QC: grounding only - no independent tool" when no second tool can check it.
"""

root_agent = LlmAgent(
    name="datapilot_external_agent",
    model=os.getenv("ADK_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.6-flash")),
    description="Answers business questions using only DataPilot's governed MCP tools, then self-checks the figures.",
    instruction=INSTRUCTION,
    tools=[datapilot_tools],
)
