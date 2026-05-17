#!/usr/bin/env bash
# Generate settings.json for the current OS.
# Output goes to stdout; caller writes to disk.
# Note: On Windows (native), hooks must be wrapped with wsl.
# Inside WSL, ~/.claude maps to the Linux home (~), not C:\Users\..\.claude.

source "${HOME}/.claude/scripts/os.sh"

if [ "$OS" = "windows" ]; then
    # Windows: wrap every hook command with wsl
    SESSION_START='wsl bash ~/.claude/hooks/session-start.sh'
    PRE_TOOL='wsl bash ~/.claude/hooks/pre-tool.sh'
    POST_TOOL='wsl bash ~/.claude/hooks/post-tool.sh'
    PRE_COMPACT='wsl bash ~/.claude/hooks/pre-compact.sh'
    STOP='wsl bash ~/.claude/hooks/stop.sh'
    TOKEN_BUDGET='wsl bash ~/.claude/scripts/token-budget.sh'
    STATUS_LINE='wsl bash ~/.claude/scripts/statusline.sh'
else
    # macOS / Linux: direct bash paths
    CLAUDE_DIR="${HOME}/.claude"
    SESSION_START="bash ${CLAUDE_DIR}/hooks/session-start.sh"
    PRE_TOOL="bash ${CLAUDE_DIR}/hooks/pre-tool.sh"
    POST_TOOL="bash ${CLAUDE_DIR}/hooks/post-tool.sh"
    PRE_COMPACT="bash ${CLAUDE_DIR}/hooks/pre-compact.sh"
    STOP="bash ${CLAUDE_DIR}/hooks/stop.sh"
    TOKEN_BUDGET="bash ${CLAUDE_DIR}/scripts/token-budget.sh"
    STATUS_LINE="bash ${CLAUDE_DIR}/scripts/statusline.sh"
fi

cat <<JSON
{
  "autoUpdatesChannel": "latest",
  "theme": "auto",
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${SESSION_START}",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "${PRE_TOOL}",
            "timeout": 30
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "${POST_TOOL}",
            "timeout": 30
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${PRE_COMPACT}",
            "timeout": 60
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${STOP}",
            "timeout": 30
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${TOKEN_BUDGET}",
            "timeout": 5
          }
        ]
      }
    ]
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
      "Touching files I shouldn't..."
    ]
  },
  "spinnerTipsEnabled": true,
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
      "context used% > 60 = compact now"
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "${STATUS_LINE}"
  },
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"],
      "scope": "user"
    }
  }
}
JSON
