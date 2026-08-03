from __future__ import annotations

import argparse
import json

from datapilot_client import invoke_registered_tool, search_registered_tools


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and invoke a governed account tool")
    parser.add_argument("--tool", default="accounts.count_since")
    parser.add_argument("--parameters", default='{"minimum_id": 50150}')
    args = parser.parse_args()

    registry = search_registered_tools("account")
    matching = next((tool for tool in registry["tools"] if tool["name"] == args.tool), None)
    if matching is None:
        raise SystemExit(f"Granted tool not found: {args.tool}")
    result = invoke_registered_tool(args.tool, json.loads(args.parameters))
    print(json.dumps({"tool": matching, "result": result}, indent=2, default=str))


if __name__ == "__main__":
    main()
