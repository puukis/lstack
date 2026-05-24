#!/usr/bin/env python3
"""LBrain capture hook wrapper.

Usage:
  lbrain-capture-hook.py post-tool
  lbrain-capture-hook.py doctor
  lbrain-capture-hook.py self-check

Reads a Claude Code hook JSON payload from stdin (post-tool subcommand)
and records capture events via the LBrain autolearn pipeline.

Always exits 0 to fail open and never block normal Claude tool use.
No LLM calls. No subprocess spawning of AI tools.
"""

import json
import os
import sys
from pathlib import Path


def _setup_path():
    script_dir = Path(__file__).resolve().parent
    lbrain_dir = script_dir.parent / "lbrain"
    lbrain_str = str(lbrain_dir)
    if lbrain_str not in sys.path:
        sys.path.insert(0, lbrain_str)


def _debug_log(msg):
    if os.environ.get("LSTACK_BRAIN_AUTO_LEARN_DEBUG", "0") != "0":
        print(f"[lbrain-capture-hook] {msg}", file=sys.stderr)


def cmd_post_tool():
    raw = sys.stdin.read()
    if not raw.strip():
        _debug_log("empty stdin, skipping")
        return

    try:
        payload = json.loads(raw)
    except Exception as exc:
        _debug_log(f"malformed JSON: {exc}")
        return

    if not isinstance(payload, dict):
        _debug_log("payload is not a dict, skipping")
        return

    _setup_path()
    try:
        from brain.autolearn import process_hook_payload
        result = process_hook_payload(payload)
        status = result.get("status", "unknown")
        _debug_log(f"result: {status}")
        if status == "ok":
            results = result.get("results", [])
            for r in results:
                evt = r.get("event") or {}
                cand = r.get("candidate") or {}
                _debug_log(
                    f"  event {evt.get('id')} ({evt.get('event_type')})"
                    + (f" -> candidate {cand.get('id')} status={cand.get('status')}" if cand else "")
                )
    except Exception as exc:
        _debug_log(f"process_hook_payload error: {exc}")


def cmd_self_check():
    _setup_path()
    try:
        from brain.autolearn import autolearn_config
        config = autolearn_config()
        print(json.dumps(config))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "status": "fail"}))


def main():
    args = sys.argv[1:]
    subcmd = args[0] if args else "post-tool"

    try:
        if subcmd in ("self-check", "doctor"):
            cmd_self_check()
        else:
            cmd_post_tool()
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
