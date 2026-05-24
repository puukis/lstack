#!/usr/bin/env bash
# Generate settings.json for the current OS.

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"

if [ "${PYTHON_AVAILABLE:-false}" != "true" ]; then
    printf 'lstack needs Python 3 to generate settings.json. Install Python from python.org or make sure `py -3` works in Git Bash.\n' >&2
    exit 1
fi

if [ "${PYTHON_MODE:-}" = "py-launcher" ]; then
    MCP_COMMAND="py"
    MCP_ARGS_PREFIX="-3"
else
    MCP_COMMAND="${PYTHON_EXE}"
    MCP_ARGS_PREFIX=""
fi

export LSTACK_GEN_OS="${OS}"
export LSTACK_GEN_CLAUDE_DIR="${CLAUDE_DIR}"
export LSTACK_GEN_MCP_COMMAND="${MCP_COMMAND}"
export LSTACK_GEN_MCP_ARGS_PREFIX="${MCP_ARGS_PREFIX}"

run_python - <<'PY'
import json
import os

claude_dir = os.environ["LSTACK_GEN_CLAUDE_DIR"]
mcp_command = os.environ["LSTACK_GEN_MCP_COMMAND"]
mcp_args_prefix = os.environ.get("LSTACK_GEN_MCP_ARGS_PREFIX") or ""

session_start = f"bash {claude_dir}/hooks/session-start.sh"
pre_tool = f"bash {claude_dir}/hooks/pre-tool.sh"
post_tool = f"bash {claude_dir}/hooks/post-tool.sh"
pre_compact = f"bash {claude_dir}/hooks/pre-compact.sh"
stop = f"bash {claude_dir}/hooks/stop.sh"
token_budget = f"bash {claude_dir}/scripts/token-budget.sh"
status_line = f"bash {claude_dir}/scripts/statusline.sh"

mcp_args = []
if mcp_args_prefix:
    mcp_args.append(mcp_args_prefix)
mcp_args.append(f"{claude_dir}/scripts/mcp_server.py")

settings = {
    "autoUpdatesChannel": "latest",
    "theme": "auto",
    "hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": session_start, "timeout": 10}]}],
        "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": pre_tool, "timeout": 30}]}],
        "PostToolUse": [{"matcher": "Bash|Write|Edit|MultiEdit", "hooks": [{"type": "command", "command": post_tool, "timeout": 30}]}],
        "PreCompact": [{"hooks": [{"type": "command", "command": pre_compact, "timeout": 60}]}],
        "Stop": [{"hooks": [{"type": "command", "command": stop, "timeout": 90}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": token_budget, "timeout": 5}]}],
    },
    "spinnerVerbs": {
        "mode": "replace",
        "verbs": [
            "Hallucinating confidently...",
            "Pretending to read your code...",
            "Blaming the context window...",
            "Adding technical debt...",
            "Consulting training data from 2024...",
            "Vibing with your spaghetti...",
            "Making things worse before better...",
            "Definitely not looping...",
            "Speedrunning your codebase...",
            "Inventing a new bug...",
            "Forgetting what you said earlier...",
            "Overthinking a one-liner...",
            "Burning your token budget...",
            "Approximately solving this...",
            "Summoning a confident wrong answer...",
            "Staring into the void...",
            "Doing my best (low bar)...",
            "Not reading the docs...",
            "Copying from Stack Overflow internally...",
            "Touching files I shouldn't...",
        ],
    },
    "spinnerTipsEnabled": True,
    "spinnerTipsOverride": {
        "mode": "replace",
        "tips": [
            "Run /compact at 60% context - not when forced",
            "Use /planner before writing any code",
            "PreCompact hook auto-saves a handover summary",
            "Loop detected 3x = stop and ask, never retry blind",
            "Skills are on-demand: /engineer /reviewer /debug /ship",
            "Stop hook runs your tests before Claude can finish",
            "Project memory lives in .claude/memory/ - Claude keeps it updated",
            "lstack logs shows every tool call this session",
            "Use /refactor after features ship, not during",
            "context used% > 60 = compact now",
        ],
    },
    "statusLine": {"type": "command", "command": status_line},
    "mcpServers": {
        "context7": {
            "command": "npx",
            "args": ["-y", "@upstash/context7-mcp"],
            "scope": "user",
        },
        "lstack": {
            "command": mcp_command,
            "args": mcp_args,
            "scope": "user",
        },
    },
}

print(json.dumps(settings, indent=2))
PY
