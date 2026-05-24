#!/usr/bin/env python3
"""Stop hook implementation for test enforcement and marker extraction."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_TYPES = {
    "pattern",
    "pitfall",
    "preference",
    "architecture",
    "tool",
    "operational",
    "investigation",
}
ALLOWED_SOURCES = {"observed", "user-stated", "inferred", "cross-model"}
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
MARKER_RE = re.compile(
    r"\[LSTACK_LEARNING\](.*?)\[/LSTACK_LEARNING\]",
    re.IGNORECASE | re.DOTALL,
)
PROMPT_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|ignore\s+all\s+previous|you\s+are\s+now|"
    r"(^|\n)\s*(system|assistant|user|override)\s*:|do\s+not\s+report|"
    r"approve\s+all|skip\s+security|skip\s+all\s+checks|always\s+output\s+no\s+findings)",
    re.IGNORECASE,
)

DEFAULT_CONFIG = {
    "learning_extract_llm": False,
    "learning_extract_markers": True,
    "learning_max_markers": 5,
    "learning_stop_no_embed": True,
}


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_DIR", str(Path.home() / ".claude")))


def log_dir() -> Path:
    return Path(os.environ.get("LSTACK_LOG_DIR", str(claude_dir() / "logs")))


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def db_py() -> Path:
    candidate = script_dir() / "db.py"
    if candidate.exists():
        return candidate
    return claude_dir() / "scripts" / "db.py"


def append_log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{iso_now()}] {message}\n")
    except Exception:
        pass


def sessions_log(message: str) -> None:
    append_log(log_dir() / "sessions.log", message)


def learn_log(message: str) -> None:
    append_log(log_dir() / "learn-extract.log", message)


def is_windowsish() -> bool:
    return os.name == "nt" or bool(os.environ.get("MSYSTEM"))


def normalize_hook_path(raw: str | None) -> str:
    if not raw:
        return ""
    p = os.path.expanduser(str(raw).strip())
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", p)
    if m and is_windowsish():
        return f"/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}"
    return p.replace("\\", "/")


def native_path_for_subprocess(path: str) -> str:
    if not path:
        return path
    m = re.match(r"^/([A-Za-z])/(.*)$", path)
    if os.name == "nt" and m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    return path


def path_exists(path: str) -> bool:
    if not path:
        return False
    return Path(native_path_for_subprocess(path)).exists()


def safe_session_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value or "unknown").strip("-")
    return cleaned[:120] or "unknown"


def state_path(session_id: str) -> Path:
    return log_dir() / f"stop-state-{safe_session_id(session_id)}.json"


def load_state(session_id: str) -> dict:
    path = state_path(session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(session_id: str, state: dict) -> None:
    state["session_id"] = session_id
    state["updated_at"] = iso_now()
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    for path in (
        claude_dir() / "memory" / "config.json",
        claude_dir() / "memory" / "lstack-config.json",
    ):
        try:
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    cfg.update({k: raw[k] for k in DEFAULT_CONFIG if k in raw})
        except Exception as exc:
            learn_log(f"config read failed path={path} error={type(exc).__name__}")
    try:
        cfg["learning_max_markers"] = max(0, min(5, int(cfg["learning_max_markers"])))
    except Exception:
        cfg["learning_max_markers"] = 5
    cfg["learning_extract_llm"] = bool(cfg.get("learning_extract_llm", False))
    cfg["learning_extract_markers"] = bool(cfg.get("learning_extract_markers", True))
    cfg["learning_stop_no_embed"] = bool(cfg.get("learning_stop_no_embed", True))
    return cfg


def parse_payload(raw_input: str) -> dict:
    try:
        data = json.loads(raw_input or "{}")
        if not isinstance(data, dict):
            data = {}
    except Exception as exc:
        sessions_log(f"STOP json-parse-failed error={type(exc).__name__}")
        data = {}

    cwd_raw = data.get("cwd") or os.getcwd()
    transcript_raw = data.get("transcript_path") or ""
    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        session_id = str(os.getppid())
        sessions_log(f"STOP missing-session-id fallback=ppid value={session_id}")

    parsed = {
        "hook_event_name": data.get("hook_event_name") or "",
        "session_id": session_id,
        "transcript_path_raw": str(transcript_raw),
        "transcript_path": normalize_hook_path(str(transcript_raw)),
        "cwd_raw": str(cwd_raw),
        "cwd": normalize_hook_path(str(cwd_raw)),
        "stop_hook_active": bool(data.get("stop_hook_active", False)),
        "last_assistant_message": str(data.get("last_assistant_message") or ""),
    }
    sessions_log(f"STOP start session_id={parsed['session_id']}")
    sessions_log(f"STOP raw_cwd={clamp(parsed['cwd_raw'])}")
    sessions_log(f"STOP normalized_cwd={clamp(parsed['cwd'])}")
    sessions_log(f"STOP raw_transcript_path={clamp(parsed['transcript_path_raw'])}")
    sessions_log(f"STOP normalized_transcript_path={clamp(parsed['transcript_path'])}")
    sessions_log(f"STOP stop_hook_active={str(parsed['stop_hook_active']).lower()}")
    sessions_log("STOP python_available=true")
    return parsed


def clamp(value: str, limit: int = 500) -> str:
    value = re.sub(r"[\r\n]+", " ", str(value))
    if len(value) > limit:
        return value[:limit] + "...[clamped]"
    return value


def find_git_root(cwd: str) -> str:
    native_cwd = native_path_for_subprocess(cwd) or os.getcwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=native_cwd,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return normalize_hook_path(result.stdout.strip())
    except Exception as exc:
        sessions_log(f"STOP git-root-error error={type(exc).__name__}")
    return ""


def find_test_cmd(git_root: str) -> str:
    if not git_root:
        return ""
    claude_md = Path(native_path_for_subprocess(git_root)) / ".claude" / "CLAUDE.md"
    try:
        lines = claude_md.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    in_section = False
    for line in lines:
        if re.match(r"^##\s+Build\s*&\s*Test\s*$", line):
            in_section = True
            continue
        if line.startswith("## "):
            in_section = False
        if in_section:
            m = re.match(r"^\s*test:\s*(.+?)\s*$", line)
            if m:
                return m.group(1)
    return ""


def run_tests(git_root: str, test_cmd: str) -> tuple[int, str]:
    if not test_cmd:
        return 0, ""
    try:
        result = subprocess.run(
            ["bash", "-c", test_cmd],
            cwd=native_path_for_subprocess(git_root),
            text=True,
            capture_output=True,
            timeout=None,
            check=False,
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        return 127, f"Could not run test command: {type(exc).__name__}: {exc}"


def parse_marker_body(body: str) -> dict:
    item: dict[str, str] = {}
    current_key = None
    for raw_line in body.replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            current_key = m.group(1).lower()
            item[current_key] = m.group(2).strip()
        elif current_key:
            item[current_key] = f"{item[current_key]}\n{line.strip()}".strip()
    return item


def validate_marker(item: dict) -> tuple[dict | None, str | None]:
    learning_type = (item.get("type") or "").strip()
    source = (item.get("source") or "").strip()
    key = (item.get("key") or "").strip()
    insight = re.sub(r"\s+", " ", (item.get("insight") or "").strip())
    confidence_raw = (item.get("confidence") or "").strip()

    if learning_type not in ALLOWED_TYPES:
        return None, f"invalid type: {learning_type}"
    if source not in ALLOWED_SOURCES:
        return None, f"invalid source: {source}"
    if not KEY_RE.match(key):
        return None, f"invalid key: {key}"
    if not insight:
        return None, "empty insight"
    if len(insight) > 1000:
        return None, "insight too long"
    if PROMPT_INJECTION_RE.search(insight):
        return None, "unsafe instruction-like insight"
    try:
        confidence = int(confidence_raw)
    except Exception:
        return None, "invalid confidence"
    if confidence < 1 or confidence > 10:
        return None, "invalid confidence"
    return {
        "type": learning_type,
        "source": source,
        "key": key,
        "insight": insight,
        "confidence": confidence,
    }, None


def extract_markers(text: str, max_markers: int) -> tuple[list[dict], int, int]:
    matches = MARKER_RE.findall(text or "")
    found = len(matches)
    valid: list[dict] = []
    skipped = 0
    for idx, body in enumerate(matches[:max_markers], start=1):
        item = parse_marker_body(body)
        clean, reason = validate_marker(item)
        if clean:
            valid.append(clean)
        else:
            skipped += 1
            learn_log(f"marker rejected index={idx} reason={reason}")
    if found > max_markers:
        skipped += found - max_markers
        learn_log(f"marker limit reached found={found} max={max_markers}")
    return valid, found, skipped


def store_marker(marker: dict, session_id: str, project: str, no_embed: bool) -> bool:
    content = f"[{marker['type']}/{marker['key']}] {marker['insight']}"
    tags = ",".join(["lstack-learning", marker["type"], marker["source"], marker["key"]])
    cmd = [
        sys.executable,
        str(db_py()),
        "observe",
        session_id,
        project,
        content,
        tags,
    ]
    if no_embed:
        cmd.append("--no-embed")
    env = os.environ.copy()
    if no_embed:
        env["LSTACK_NO_EMBED"] = "1"
    try:
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
            env=env,
        )
        if result.stderr:
            learn_log(f"db stderr key={marker['key']} stderr={clamp(result.stderr, 1000)}")
        if result.returncode == 0:
            learn_log(f"db write ok key={marker['key']}")
            return True
        learn_log(f"db write failed key={marker['key']} rc={result.returncode}")
    except Exception as exc:
        learn_log(f"db write exception key={marker['key']} error={type(exc).__name__}: {exc}")
    return False


def run_learning_extraction(parsed: dict, git_root: str, state: dict, config: dict) -> dict:
    if parsed["stop_hook_active"] and state.get("learning_extraction_ran"):
        sessions_log("STOP learning skipped reason=already-ran")
        return {"found": 0, "attempted": 0, "stored": 0, "skipped": 0, "failed": 0}

    if not config.get("learning_extract_markers", True):
        sessions_log("STOP no learnings stored reason=marker-extraction-disabled")
        learn_log("marker extraction disabled by config")
        state["learning_extraction_ran"] = True
        return {"found": 0, "attempted": 0, "stored": 0, "skipped": 0, "failed": 0}

    if config.get("learning_extract_llm", False):
        if os.environ.get("LSTACK_INSIDE_HOOK"):
            learn_log("LLM extraction requested but skipped by recursion guard")
        else:
            learn_log("LLM extraction requested but disabled stub active")

    if parsed["transcript_path"] and not path_exists(parsed["transcript_path"]):
        learn_log(
            "transcript missing "
            f"raw={clamp(parsed['transcript_path_raw'])} "
            f"normalized={clamp(parsed['transcript_path'])} reason=not-found"
        )

    markers, found, skipped = extract_markers(
        parsed.get("last_assistant_message") or "",
        int(config.get("learning_max_markers", 5)),
    )
    learn_log(f"marker_blocks_found={found} valid={len(markers)} skipped={skipped}")
    if found == 0:
        sessions_log("STOP no learnings stored reason=no explicit learning markers found")
        learn_log("no explicit learning markers found")
        state["learning_extraction_ran"] = True
        return {"found": 0, "attempted": 0, "stored": 0, "skipped": 0, "failed": 0}

    project = git_root or parsed["cwd"] or "unknown"
    stored = 0
    failed = 0
    for marker in markers:
        if store_marker(marker, parsed["session_id"], project, config.get("learning_stop_no_embed", True)):
            stored += 1
        else:
            failed += 1

    attempted = len(markers)
    if stored > 0:
        sessions_log(f"STOP learning-extracted stored={stored}")
    else:
        sessions_log("STOP no learnings stored reason=no-valid-marker-stored")
    learn_log(
        f"summary marker_blocks_found={found} attempted={attempted} "
        f"stored={stored} skipped={skipped} failed={failed}"
    )
    state["learning_extraction_ran"] = True
    return {
        "found": found,
        "attempted": attempted,
        "stored": stored,
        "skipped": skipped,
        "failed": failed,
    }


def handle(raw_input: str) -> int:
    os.environ["LSTACK_INSIDE_HOOK"] = "1"
    parsed = parse_payload(raw_input)
    state = load_state(parsed["session_id"])
    config = load_config()

    git_root = find_git_root(parsed["cwd"])
    if not git_root:
        sessions_log("STOP no-git-root")
    test_cmd = find_test_cmd(git_root)
    if not test_cmd:
        sessions_log("STOP no-test-cmd found")

    run_learning_extraction(parsed, git_root, state, config)

    if not test_cmd:
        state["last_test_status"] = "no-test-cmd"
        state["last_test_cmd"] = ""
        state["block_count"] = int(state.get("block_count") or 0)
        save_state(parsed["session_id"], state)
        return 0

    test_rc, test_output = run_tests(git_root, test_cmd)
    state["last_test_cmd"] = test_cmd
    state["last_test_status"] = "passed" if test_rc == 0 else "failed"

    if test_rc == 0:
        state["block_count"] = 0
        sessions_log(f"STOP tests-passed cmd={clamp(test_cmd)}")
        save_state(parsed["session_id"], state)
        return 0

    block_count = int(state.get("block_count") or 0) + 1
    state["block_count"] = block_count
    sessions_log(f"STOP tests-failed cmd={clamp(test_cmd)} rc={test_rc} block_count={block_count}")
    save_state(parsed["session_id"], state)

    tail = "\n".join(test_output.splitlines()[-20:])
    if block_count > 3:
        msg = "tests still failing, not blocking again to avoid infinite Stop loop"
        sessions_log("STOP tests-failed unblock-after-limit")
        print(f"{msg}\n{tail}".strip())
        return 0
    print(f"Tests failed. Fix before finishing:\n{tail}".strip())
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalize-path")
    parser.add_argument("--extract-markers", action="store_true")
    parser.add_argument("--max-markers", type=int, default=5)
    args = parser.parse_args(argv)

    if args.normalize_path is not None:
        print(normalize_hook_path(args.normalize_path))
        return 0
    if args.extract_markers:
        markers, found, skipped = extract_markers(sys.stdin.read(), args.max_markers)
        print(json.dumps({"found": found, "valid": markers, "skipped": skipped}, sort_keys=True))
        return 0
    return handle(sys.stdin.read())


if __name__ == "__main__":
    raise SystemExit(main())
