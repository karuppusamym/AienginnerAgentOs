"""Run the Google ADK variant (adk_agent/) on one question and print each step.

Uses the isolated venv (google-adk + mcp live only there):

    .venv\\Scripts\\python run_adk.py "What is the total amount of settled payments?"     (Windows)
    .venv/bin/python run_adk.py "What is the total amount of settled payments?"          (macOS/Linux)

Same thing through the ADK CLI:  .venv\\Scripts\\adk run adk_agent   (or: adk web)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import warnings

warnings.filterwarnings("ignore")  # ADK prints [EXPERIMENTAL] feature warnings
logging.getLogger("google_adk").setLevel(logging.ERROR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from adk_agent.agent import DATAPILOT_API, datapilot_tools, root_agent  # noqa: E402


def _summarize_response(response: object) -> str:
    """tools/call result -> 'N row(s), invocation <id>' (the full rows go to the model, not the console)."""
    payload = response if isinstance(response, dict) else {}
    structured = payload.get("structuredContent")
    if structured is None and payload.get("content"):
        try:
            structured = json.loads(payload["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError):
            structured = None
    if isinstance(structured, dict) and "row_count" in structured:
        return f"{structured['row_count']} row(s), invocation {structured.get('invocation_id')}"
    return json.dumps(payload, default=str)[:300]


async def main(question: str) -> int:
    print(f"DataPilot external agent (Google ADK + McpToolset, model {root_agent.model})  -> {DATAPILOT_API}/mcp")
    tools = await datapilot_tools.get_tools()
    print(f"\n[1] McpToolset connected (initialize + tools/list): {len(tools)} tool(s)")
    for tool in tools:
        print(f"    - {tool.name}")
    runner = InMemoryRunner(agent=root_agent, app_name="datapilot_external_adk")
    session = await runner.session_service.create_session(app_name="datapilot_external_adk", user_id="demo")
    print(f'\n[2] Question: "{question}"')
    step = 2
    final = ""
    try:
        async for event in runner.run_async(
            user_id="demo",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=question)]),
        ):
            for part in (event.content.parts if event.content and event.content.parts else []):
                if part.function_call:
                    step += 1
                    print(f"\n[{step}] Gemini -> tools/call {part.function_call.name}({json.dumps(dict(part.function_call.args or {}))})")
                elif part.function_response:
                    print(f"    <- {part.function_response.name}: {_summarize_response(part.function_response.response)}")
                elif part.text and event.is_final_response():
                    final += part.text
    finally:
        await datapilot_tools.close()
    print(f"\n[{step + 1}] Answer\n" + "\n".join("    " + line for line in final.strip().splitlines()))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('usage: run_adk.py "question"')
    sys.exit(asyncio.run(main(" ".join(sys.argv[1:]))))
