"""Local action audit log — append-only JSON Lines file."""

import datetime
import json
import os
from pathlib import Path

AUDIT_LOG_PATH = Path(os.environ.get(
    "LSTACK_AUDIT_LOG",
    str(Path.home() / ".claude" / "logs" / "dashboard-audit.jsonl"),
))


def _iso_now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def write_audit_entry(
    action_id: str,
    actor: str = "dashboard",
    params: dict | None = None,
    result: str = "unknown",
    error: str | None = None,
) -> dict:
    entry = {
        "ts": _iso_now(),
        "action_id": action_id,
        "actor": actor,
        "params": params or {},
        "result": result,
    }
    if error:
        entry["error"] = error
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        entry["write_error"] = str(exc)[:120]
    return entry


def read_recent_audit_entries(limit: int = 50) -> list[dict]:
    if not AUDIT_LOG_PATH.exists():
        return []
    try:
        lines = AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in reversed(lines[-limit * 2:]):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
            if len(entries) >= limit:
                break
        return entries
    except Exception:
        return []
