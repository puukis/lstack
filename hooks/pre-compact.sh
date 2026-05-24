#!/usr/bin/env bash
# PreCompact hook: generate local handover summary before context compaction.
#
# This hook intentionally does NOT call claude -p.  Spawning Claude from
# inside a lifecycle hook creates nested Claude sessions that re-trigger all
# hooks recursively.  Instead, the last few assistant messages are extracted
# directly from the session transcript using Python.

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"

mkdir -p "${LOG_DIR}"

input="$(cat)"

# Parse transcript_path and session_id via temp file (Git Bash heredoc+pipe
# interaction can overwrite stdin, so we use a temp script file instead).
_py_tmp="$(mktemp /tmp/lstack-precompact-XXXXXX.py)"
cat > "${_py_tmp}" <<'PYEOF'
import sys, json
data = {}
try:
    data = json.loads(sys.stdin.read())
except Exception:
    pass
print(data.get("transcript_path", ""))
print(data.get("session_id", ""))
PYEOF
parsed="$(printf '%s' "${input}" | run_python "${_py_tmp}" 2>/dev/null)" || true
rm -f "${_py_tmp}"

transcript_path="$(printf '%s' "${parsed}" | sed -n '1p')"
session_id="$(printf '%s' "${parsed}" | sed -n '2p')"

if [ -z "${transcript_path}" ]; then
    exit 0
fi

# Determine output path
git_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "${git_root}" ]; then
    out_dir="${git_root}/.claude/memory"
    mkdir -p "${out_dir}"
    out_path="${out_dir}/handover.md"
else
    out_path="${CLAUDE_DIR}/memory/handover.md"
fi

# Generate handover locally from the session transcript.
# Reads the last few assistant messages and writes a compact context file.
# No Claude subprocess is spawned.
if [ "${PYTHON_AVAILABLE:-false}" = "true" ]; then
    _py_handover="$(mktemp /tmp/lstack-handover-XXXXXX.py)"
    cat > "${_py_handover}" <<'PYEOF'
import sys, json, os, re
from datetime import datetime, timezone

transcript_raw = sys.argv[1] if len(sys.argv) > 1 else ""
out_raw        = sys.argv[2] if len(sys.argv) > 2 else ""
session_id     = sys.argv[3] if len(sys.argv) > 3 else "unknown"


def _normalize(raw):
    """Convert any Windows path variant to forward-slash POSIX form."""
    if not raw:
        return ""
    p = os.path.expanduser(str(raw).strip())
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", p)
    if m:
        return f"/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}"
    return p.replace("\\", "/")


def _native(path):
    """Convert /x/... Git-Bash path to C:/... for native Windows file I/O."""
    if not path:
        return path
    m = re.match(r"^/([A-Za-z])/(.*)$", path)
    if os.name == "nt" and m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    return path


transcript_path = _native(_normalize(transcript_raw))
out_path        = _native(_normalize(out_raw))

if not out_path:
    sys.exit(0)

messages = []
try:
    with open(transcript_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                # Support both flat {"role": ...} and nested {"message": {"role": ...}}
                role    = obj.get("role") or (obj.get("message") or {}).get("role", "")
                content = obj.get("content") or (obj.get("message") or {}).get("content", "")
                if role != "assistant":
                    continue
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    text = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ).strip()
                else:
                    text = ""
                if text:
                    messages.append(text)
            except Exception:
                continue
except Exception:
    pass

ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

with open(out_path, "w", encoding="utf-8") as fh:
    fh.write(f"# Handover\n\n")
    fh.write(f"Generated: {ts}  Session: {session_id}\n\n")
    if messages:
        fh.write("## Last assistant messages\n\n")
        for msg in messages[-3:]:
            snippet = msg[:500].replace("\n", " ").strip()
            if snippet:
                fh.write(f"- {snippet}\n")
    else:
        fh.write("No transcript content available at compaction time.\n")
PYEOF
    run_python "${_py_handover}" "${transcript_path}" "${out_path}" "${session_id}" 2>/dev/null || true
    rm -f "${_py_handover}"
fi

iso="$(iso_now)"
printf '[%s] %s -> %s\n' "${iso}" "${session_id}" "${out_path}" >> "${LOG_DIR}/compactions.log" 2>/dev/null || true

exit 0
