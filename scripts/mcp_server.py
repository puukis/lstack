#!/usr/bin/env python3
"""lstack MCP server — exposes memory as Claude Code tools via stdio."""

import sys
import json
import os
from pathlib import Path

# Flush stdout immediately (required for MCP stdio transport)
sys.stdout.reconfigure(line_buffering=True)

# Add lstack scripts to path
sys.path.insert(0, str(Path.home() / ".claude" / "scripts"))

TOOLS = [
    {
        "name": "memory_search",
        "description": "Search lstack persistent memory semantically. "
            "Returns relevant past observations for the current project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for"
                },
                "project": {
                    "type": "string",
                    "description": "Project path filter (optional). "
                        "Omit to search all projects including global."
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "memory_store",
        "description": "Store an observation in lstack persistent memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The observation to store (max 150 chars)"
                },
                "project": {
                    "type": "string",
                    "description": "Project path or 'global' for cross-project"
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated keywords"
                }
            },
            "required": ["content", "project"]
        }
    },
    {
        "name": "memory_stats",
        "description": "Show lstack memory database statistics.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def handle_request(req):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "lstack-memory", "version": "2.0.0"},
                "capabilities": {"tools": {}}
            }
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": TOOLS}
        }

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        try:
            import db
            result = _call_tool(tool_name, args, db)
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}],
                    "isError": False
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True
                }
            }

    if method == "notifications/initialized":
        return None  # no response needed

    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def _call_tool(name, args, db):
    if name == "memory_search":
        import argparse
        a = argparse.Namespace(
            query=args["query"],
            project=args.get("project"),
            limit=args.get("limit", 5)
        )
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            db.cmd_search(a)
        return buf.getvalue().strip()

    if name == "memory_store":
        import argparse
        a = argparse.Namespace(
            session_id="mcp",
            project=args["project"],
            content=args["content"],
            tags=args.get("tags", "")
        )
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            db.cmd_observe(a)
        return buf.getvalue().strip()

    if name == "memory_stats":
        import argparse
        a = argparse.Namespace()
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            db.cmd_stats(a)
        return buf.getvalue().strip()

    raise ValueError(f"Unknown tool: {name}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            if resp is not None:
                print(json.dumps(resp), flush=True)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": str(e)}
            }), flush=True)


if __name__ == "__main__":
    main()
