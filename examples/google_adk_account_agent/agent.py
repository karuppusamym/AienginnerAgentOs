from __future__ import annotations

import os

from google.adk.agents import Agent

from .datapilot_client import invoke_registered_tool, search_registered_tools


root_agent = Agent(
    name="governed_account_agent",
    model=os.getenv("ADK_MODEL", "gemini-3.6-flash"),
    instruction=(
        "You are an account-operations data assistant. Always search the DataPilot registry "
        "before choosing a database tool. Explain the selected tool's purpose and data source, "
        "invoke it only with parameters declared in its input schema, and display the returned "
        "rows as a compact table. Never invent a tool or send raw SQL."
    ),
    tools=[search_registered_tools, invoke_registered_tool],
)
