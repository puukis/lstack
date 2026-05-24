#!/usr/bin/env python3
"""Session-scoped lstack freeze/careful/guard safety helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
STATE_TTL_SECONDS = int(os.environ.get("LSTACK_STATE_TTL_SECONDS", str(72 * 3600)))
SAFE_RM_NAMES = {
    ".cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}
SAFE_RM_OPTIONAL_NAMES = {"out", "temp", "tmp"}
SENSITIVE_ENV_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASS|API_KEY|AUTH)[A-Z0-9_]*)=([^ \t]+)"
)


class StateLoad:
    def __init__(
        self,
        path: Path,
        data: dict[str, Any] | None = None,
        malformed: bool = False,
        stale: bool = False,
        error: str = "",
    ) -> None:
        self.path = path
        self.data = data or {}
        self.malformed = malformed
        self.stale = stale
        self.error = error


class NormalizedPath:
    def __init__(self, raw: str, display: str, key: str) -> None:
        self.raw = raw
        self.display = display
        self.key = key

    def __str__(self) -> str:
        return self.display


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def session_id() -> str:
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("LSTACK_SESSION_ID")
        or os.environ.get("LSTACK_TEST_SESSION_ID")
        or str(os.getppid())
    )


def safe_session_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:120] or "unknown"


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))


def log_dir() -> Path:
    return Path(os.environ.get("LSTACK_LOG_DIR", claude_dir() / "logs"))


def state_file(kind: str, sid: str | None = None) -> Path:
    return log_dir() / f"{kind}-{safe_session_id(sid or session_id())}.json"


def events_file() -> Path:
    return log_dir() / "safety-events.log"


def command_hash(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8", "replace")).hexdigest()[:16]


def read_json_state(kind: str, sid: str | None = None) -> StateLoad:
    path = state_file(kind, sid)
    if not path.exists():
        return StateLoad(path=path)
    try:
        mtime = path.stat().st_mtime
        stale = (datetime.now(timezone.utc).timestamp() - mtime) > STATE_TTL_SECONDS
    except OSError:
        stale = False
    if stale:
        return StateLoad(path=path, stale=True)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return StateLoad(path=path, malformed=True, error="state root is not an object")
        return StateLoad(path=path, data=data)
    except Exception as exc:  # noqa: BLE001 - state parse errors should not crash hooks
        return StateLoad(path=path, malformed=True, error=str(exc))


def write_json_state(kind: str, data: dict[str, Any], sid: str | None = None) -> Path:
    path = state_file(kind, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)
    return path


def clear_state(kind: str, sid: str | None = None) -> bool:
    path = state_file(kind, sid)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _git_bash_to_windows(value: str) -> str:
    value = value.replace("\\", "/")
    match = re.match(r"^/([A-Za-z])(?:/(.*))?$", value)
    if match:
        rest = match.group(2) or ""
        return f"{match.group(1).upper()}:/{rest}"
    match = re.match(r"^/mnt/([A-Za-z])(?:/(.*))?$", value)
    if match:
        rest = match.group(2) or ""
        return f"{match.group(1).upper()}:/{rest}"
    return value


def _looks_windows_absolute(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _windows_key(value: str, cwd: str | None) -> NormalizedPath:
    native = _git_bash_to_windows(os.path.expanduser(value))
    if not _looks_windows_absolute(native):
        base = _git_bash_to_windows(os.path.expanduser(cwd or os.getcwd()))
        if _looks_windows_absolute(base):
            native = str(Path(base) / native)
    native = native.replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/?(.*)$", native)
    if not match:
        return _posix_key(native, cwd)
    drive = match.group(1).upper()
    rest = match.group(2)
    parts: list[str] = []
    for part in rest.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    display = f"{drive}:/" + "/".join(parts)
    key = display.lower()
    if display.endswith("/") and len(display) > 3:
        display = display.rstrip("/")
        key = key.rstrip("/")
    return NormalizedPath(value, display, key)


def _posix_key(value: str, cwd: str | None) -> NormalizedPath:
    expanded = os.path.expanduser(value)
    p = Path(expanded)
    if not p.is_absolute():
        p = Path(cwd or os.getcwd()) / p
    try:
        resolved = p.resolve(strict=False)
    except Exception:
        resolved = p.absolute()
    display = str(resolved)
    key = os.path.normcase(display).replace("\\", "/")
    if len(key) > 1:
        key = key.rstrip("/")
        display = display.rstrip("\\/")
    return NormalizedPath(value, display, key)


def normalize_path(value: str, cwd: str | None = None) -> NormalizedPath:
    if not value:
        raise ValueError("empty path")
    converted = _git_bash_to_windows(value)
    cwd_converted = _git_bash_to_windows(cwd or os.getcwd())
    if _looks_windows_absolute(converted) or _looks_windows_absolute(cwd_converted):
        return _windows_key(value, cwd)
    return _posix_key(value, cwd)


def is_within_path(child: str, parent: str) -> bool:
    child_key = child.rstrip("/")
    parent_key = parent.rstrip("/")
    if child_key == parent_key:
        return True
    if parent_key.endswith(":"):
        parent_key += "/"
    return child_key.startswith(parent_key + "/")


def find_project_root(cwd: str | None = None) -> NormalizedPath:
    current = Path(cwd or os.getcwd()).resolve(strict=False)
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return normalize_path(str(candidate), cwd)
    return normalize_path(str(current), cwd)


def freeze_is_active(state: StateLoad) -> bool:
    return bool(state.data.get("active") and state.data.get("allowed_paths"))


def extract_edit_paths(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    direct = tool_input.get("file_path")
    if isinstance(direct, str) and direct:
        paths.append(direct)
    if tool_name == "MultiEdit":
        for key in ("paths", "file_paths"):
            value = tool_input.get(key)
            if isinstance(value, list):
                paths.extend([p for p in value if isinstance(p, str) and p])
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            for edit in edits:
                if isinstance(edit, dict):
                    for key in ("file_path", "path", "target_path"):
                        value = edit.get(key)
                        if isinstance(value, str) and value:
                            paths.append(value)
    return list(dict.fromkeys(paths))


def hook_output(permission: str, reason: str, additional_context: str | None = None) -> str:
    payload: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission,
            "permissionDecisionReason": reason,
        }
    }
    if additional_context:
        payload["hookSpecificOutput"]["additionalContext"] = additional_context
    return json.dumps(payload, separators=(",", ":"))


def redact_preview(command: str) -> str:
    preview = command.replace("\r", " ").replace("\n", " ")
    preview = SENSITIVE_ENV_RE.sub(r"\1=<redacted>", preview)
    preview = re.sub(
        r"(?i)(--(?:password|pass|token|secret|api-key|apikey)\s+)(\S+)",
        r"\1<redacted>",
        preview,
    )
    preview = re.sub(r"(?i)(Bearer\s+)([A-Za-z0-9._~+/=-]+)", r"\1<redacted>", preview)
    if len(preview) > 120:
        preview = preview[:117] + "..."
    return preview


def log_event(
    *,
    mode: str,
    action: str,
    tool: str,
    risk: str | None = None,
    command: str | None = None,
    path: str | None = None,
    sid: str | None = None,
) -> None:
    try:
        sid = sid or session_id()
        parts = [
            f"[{iso_now()}]",
            f"session={safe_session_id(sid)}",
            f"mode={mode}",
            f"action={action}",
            f"tool={tool}",
        ]
        if risk:
            parts.append(f"risk={risk}")
        if command is not None:
            parts.append(f"command_hash={command_hash(command)}")
            parts.append("preview=" + json.dumps(redact_preview(command)))
        if path is not None:
            parts.append("path=" + json.dumps(path))
        events_file().parent.mkdir(parents=True, exist_ok=True)
        with events_file().open("a", encoding="utf-8") as fh:
            fh.write(" ".join(parts) + "\n")
    except Exception:
        return


def shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except Exception:
        try:
            return shlex.split(command, posix=True)
        except Exception:
            return command.split()


def split_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    separators = {";", "&&", "||", "|", "\n"}
    for token in tokens:
        if token in separators or set(token) <= {";", "&", "|"}:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def strip_wrappers(segment: list[str]) -> tuple[list[str], bool]:
    tokens = list(segment)
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens.pop(0)
    sudo = False
    if tokens and tokens[0] == "sudo":
        sudo = True
        tokens.pop(0)
        while tokens and tokens[0].startswith("-"):
            tokens.pop(0)
    return tokens, sudo


def command_has_inline_confirm(command: str) -> bool:
    tokens = shell_tokens(command)
    if not tokens or any(token in {";", "&&", "||", "|"} for token in tokens):
        return False
    for token in tokens:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            return False
        key, value = token.split("=", 1)
        if key == "LSTACK_CONFIRM_DESTRUCTIVE" and value == "1":
            return True
    return False


def target_has_uncertain_expansion(target: str) -> bool:
    return any(marker in target for marker in ("$", "`", "*", "?")) or target in {
        "~",
        "$HOME",
        "${HOME}",
    }


def is_critical_target(target: str, cwd: str | None = None) -> bool:
    raw = target.strip().strip("\"'")
    if raw in {"", "/", "\\", "~", "$HOME", "${HOME}"}:
        return True
    raw_forward = _git_bash_to_windows(raw).replace("\\", "/").rstrip("/")
    if re.match(r"^[A-Za-z]:$", raw_forward):
        return True
    lowered = raw_forward.lower()
    critical = {
        "/home",
        "/users",
        "c:/users",
        os.path.expanduser("~").replace("\\", "/").rstrip("/").lower(),
    }
    if lowered in critical:
        return True
    try:
        norm = normalize_path(raw, cwd)
    except Exception:
        return False
    if norm.key in {"/", "\\"}:
        return True
    if re.match(r"^[a-z]:/?$", norm.key):
        return True
    return norm.key in critical


def is_rust_project(root: NormalizedPath) -> bool:
    candidates = [root.display]
    match = re.match(r"^([A-Za-z]):/(.*)$", root.display.replace("\\", "/"))
    if match:
        drive = match.group(1).lower()
        rest = match.group(2)
        candidates.extend([f"/mnt/{drive}/{rest}", f"/{drive}/{rest}"])
    for candidate in candidates:
        try:
            if (Path(candidate) / "Cargo.toml").exists():
                return True
        except Exception:
            continue
    return False


def is_safe_generated_target(target: str, cwd: str | None = None) -> bool:
    if target_has_uncertain_expansion(target) or is_critical_target(target, cwd):
        return False
    try:
        norm = normalize_path(target, cwd)
        root = find_project_root(cwd)
    except Exception:
        return False
    if not is_within_path(norm.key, root.key):
        return False
    name = Path(norm.display.replace("\\", "/")).name
    if name in SAFE_RM_NAMES:
        return True
    if name == "target" and is_rust_project(root):
        return True
    if name in SAFE_RM_OPTIONAL_NAMES:
        return True
    return False


def parse_rm(segment: list[str]) -> tuple[bool, list[str]]:
    recursive = False
    targets: list[str] = []
    end_options = False
    for token in segment[1:]:
        if token == "--":
            end_options = True
            continue
        if not end_options and token.startswith("-"):
            if token == "--recursive":
                recursive = True
            elif token.startswith("--"):
                continue
            elif "r" in token[1:] or "R" in token[1:]:
                recursive = True
            continue
        targets.append(token)
    return recursive, targets


def has_flag(tokens: list[str], *flags: str) -> bool:
    return any(token in flags for token in tokens)


def kubectl_namespace(tokens: list[str]) -> str:
    for i, token in enumerate(tokens):
        if token in {"-n", "--namespace"} and i + 1 < len(tokens):
            return tokens[i + 1].lower()
        if token.startswith("--namespace="):
            return token.split("=", 1)[1].lower()
    return ""


def add_risk(
    risks: list[dict[str, str]],
    risk_id: str,
    message: str,
    severity: str = "high",
) -> None:
    risks.append({"id": risk_id, "message": message, "severity": severity})


def analyze_command(command: str, cwd: str | None = None) -> dict[str, Any]:
    lower = command.lower()
    risks: list[dict[str, str]] = []
    hard: list[dict[str, str]] = []

    def hard_risk(risk_id: str, message: str) -> None:
        hard.append({"id": risk_id, "message": message, "severity": "critical"})

    if re.search(r":\(\)\s*\{:", command) or ":(){:" in command:
        hard_risk("fork-bomb", "fork bomb pattern detected")
    if re.search(r"\bdrop\s+database\b", lower):
        hard_risk("drop-database", "DROP DATABASE detected")
    if re.search(r"\bdrop\s+table\b", lower):
        hard_risk("drop-table", "DROP TABLE detected")
    if re.search(r"\btruncate(?:\s+table)?\s+[A-Za-z_]", lower):
        hard_risk("truncate", "TRUNCATE detected")

    tokens = shell_tokens(command)
    segments = split_segments(tokens)
    for original_segment in segments:
        segment, sudo = strip_wrappers(original_segment)
        if not segment:
            continue
        cmd = segment[0]
        base = Path(cmd.replace("\\", "/")).name.lower()

        if base == "pnpm" and len(segment) >= 3 and segment[1:3] == ["store", "prune"]:
            continue

        if base == "rm":
            recursive, targets = parse_rm(segment)
            if sudo:
                hard_risk("sudo-rm", "sudo rm detected")
            if recursive:
                if any(is_critical_target(target, cwd) for target in targets):
                    hard_risk("rm-recursive-critical", "recursive delete targets a root, home, user, or drive boundary")
                elif targets and all(is_safe_generated_target(target, cwd) for target in targets):
                    continue
                else:
                    add_risk(risks, "rm-recursive", "recursive delete detected")

        if base.startswith("mkfs"):
            hard_risk("mkfs", "filesystem format command detected")

        if base == "dd" and any(t.startswith("of=/dev/") or t.startswith("of=\\\\.\\") for t in segment):
            hard_risk("dd-device-write", "dd writes directly to a device")

        if base == "git" and len(segment) >= 2:
            sub = segment[1]
            rest = segment[2:]
            if sub == "push":
                if "--force-with-lease" in rest:
                    continue
                if "--force" in rest:
                    hard_risk("git-force-push", "git push --force detected")
                elif "-f" in rest:
                    add_risk(risks, "git-force-push-short", "git push -f detected")
            elif sub == "reset" and "--hard" in rest:
                add_risk(risks, "git-reset-hard", "git reset --hard detected")
            elif sub == "checkout" and "." in rest:
                add_risk(risks, "git-checkout-dot", "git checkout . detected")
            elif sub == "restore" and "." in rest:
                add_risk(risks, "git-restore-dot", "git restore . detected")
            elif sub == "clean" and any("f" in t and "d" in t for t in rest if t.startswith("-")):
                add_risk(risks, "git-clean", "git clean -fd detected")

        if base in {"docker", "docker.exe"} and len(segment) >= 2:
            sub = segment[1]
            rest = segment[2:]
            if sub == "rm" and "-f" in rest:
                add_risk(risks, "docker-rm-force", "docker rm -f detected")
            elif sub == "system" and rest[:1] == ["prune"]:
                add_risk(risks, "docker-system-prune", "docker system prune detected")
            elif sub == "volume" and rest[:1] in (["rm"], ["prune"]):
                add_risk(risks, "docker-volume", "docker volume destructive command detected")
            elif sub == "compose" and rest[:1] == ["down"] and "-v" in rest:
                add_risk(risks, "docker-compose-down-volume", "docker compose down -v detected")

        if base == "docker-compose" and len(segment) >= 2:
            if segment[1] == "down" and "-v" in segment[2:]:
                add_risk(risks, "docker-compose-down-volume", "docker compose down -v detected")

        if base == "kubectl" and len(segment) >= 2:
            sub = segment[1]
            namespace = kubectl_namespace(segment)
            if sub == "delete":
                add_risk(risks, "kubectl-delete", "kubectl delete detected")
            elif sub == "apply" and namespace in {"prod", "production"}:
                add_risk(risks, "kubectl-apply-production", "kubectl apply targets a production namespace")

        if base == "chmod" and "777" in segment and any(t in {"-R", "-r"} for t in segment):
            add_risk(risks, "chmod-recursive-777", "chmod -R 777 detected")

        if base == "chown" and any(t in {"-R", "-r"} for t in segment):
            add_risk(risks, "chown-recursive", "recursive chown detected")

        if base == "killall":
            add_risk(risks, "killall", "killall detected")

        if base == "pkill" and "-f" in segment[1:]:
            add_risk(risks, "pkill-f", "pkill -f detected")

        if base == "brew" and len(segment) >= 2 and segment[1] == "uninstall":
            add_risk(risks, "brew-uninstall", "brew uninstall detected", "medium")

        if base == "npm" and len(segment) >= 2:
            sub = segment[1]
            if sub in {"uninstall", "remove", "rm"} and len(segment) > 2:
                if (Path(cwd or os.getcwd()) / "package.json").exists():
                    add_risk(risks, "npm-uninstall", "npm uninstall may modify package dependencies", "medium")
            elif sub == "cache" and "clean" in segment and "--force" in segment:
                add_risk(risks, "npm-cache-clean-force", "npm cache clean --force detected", "medium")

    seen: set[str] = set()
    deduped_risks: list[dict[str, str]] = []
    for risk in risks:
        if risk["id"] not in seen:
            deduped_risks.append(risk)
            seen.add(risk["id"])
    seen.clear()
    deduped_hard: list[dict[str, str]] = []
    for risk in hard:
        if risk["id"] not in seen:
            deduped_hard.append(risk)
            seen.add(risk["id"])
    return {"risks": deduped_risks, "hard": deduped_hard, "hash": command_hash(command)}


def load_safety_mode(sid: str | None = None) -> tuple[str, StateLoad]:
    state = read_json_state("safety", sid)
    if state.malformed or state.stale:
        return "off", state
    mode = state.data.get("mode", "off")
    if not state.data.get("active") or mode not in {"careful", "strict"}:
        return "off", state
    return str(mode), state


def consume_allow_once(state: StateLoad, cmd_hash: str) -> bool:
    allow_once = state.data.get("allow_once")
    if not isinstance(allow_once, list) or cmd_hash not in allow_once:
        return False
    state.data["allow_once"] = [item for item in allow_once if item != cmd_hash]
    write_json_state("safety", state.data)
    return True


def bash_hook_decision(tool_input: dict[str, Any], sid: str | None = None) -> str | None:
    command = tool_input.get("command", "")
    if not isinstance(command, str) or not command.strip():
        return None
    sid = sid or session_id()
    analysis = analyze_command(command)
    hard = analysis["hard"]
    risks = analysis["risks"]
    cmd_hash = analysis["hash"]
    if hard:
        risk = hard[0]
        reason = (
            f"Blocked by lstack global safety gate ({risk['id']}): "
            f"{risk['message']}. Command hash: {cmd_hash}."
        )
        log_event(mode="global", action="deny", tool="Bash", risk=risk["id"], command=command, sid=sid)
        return hook_output("deny", reason)

    mode, safety_state = load_safety_mode(sid)
    if mode == "off" or not risks:
        return None

    if (
        os.environ.get("LSTACK_CONFIRM_DESTRUCTIVE") == "1"
        or command_has_inline_confirm(command)
        or consume_allow_once(safety_state, cmd_hash)
    ):
        log_event(mode=mode, action="allow", tool="Bash", risk=risks[0]["id"], command=command, sid=sid)
        return None

    risk_ids = ", ".join(risk["id"] for risk in risks)
    risk_messages = "; ".join(risk["message"] for risk in risks)
    preview = redact_preview(command)
    if mode == "strict":
        reason = (
            f"Strict safety mode: blocked risky Bash command ({risk_ids}). "
            f"{risk_messages}. Command hash: {cmd_hash}. Preview: {preview}"
        )
        log_event(mode=mode, action="deny", tool="Bash", risk=risks[0]["id"], command=command, sid=sid)
        return hook_output("deny", reason)

    reason = (
        f"Careful safety mode: risky Bash command detected ({risk_ids}). "
        f"{risk_messages}. Command hash: {cmd_hash}. Preview: {preview}"
    )
    log_event(mode=mode, action="ask", tool="Bash", risk=risks[0]["id"], command=command, sid=sid)
    return hook_output("ask", reason)


def freeze_hook_decision(tool_name: str, tool_input: dict[str, Any], sid: str | None = None) -> str | None:
    if tool_name not in EDIT_TOOLS:
        return None
    sid = sid or session_id()
    freeze_state = read_json_state("freeze", sid)
    if freeze_state.stale:
        return None
    if freeze_state.malformed:
        reason = (
            f"Freeze active but state file is malformed: {freeze_state.path}. "
            f"Blocked edit until state is fixed or lstack unfreeze is run. Error: {freeze_state.error}"
        )
        log_event(mode="freeze", action="deny", tool=tool_name, path=str(freeze_state.path), sid=sid)
        return hook_output("deny", reason)
    if not freeze_is_active(freeze_state):
        return None

    raw_paths = extract_edit_paths(tool_name, tool_input)
    allowed_raw = [p for p in freeze_state.data.get("allowed_paths", []) if isinstance(p, str)]
    allowed: list[NormalizedPath] = []
    for path in allowed_raw:
        try:
            allowed.append(normalize_path(path))
        except Exception:
            continue
    allowed_display = ", ".join(path.display for path in allowed) or ", ".join(allowed_raw)
    if not raw_paths:
        reason = (
            f"Freeze active: edits are restricted to {allowed_display}. "
            "Blocked edit because the hook could not determine a target path. "
            "Run lstack unfreeze or lstack freeze <path> to change this."
        )
        log_event(mode="freeze", action="deny", tool=tool_name, path="<unknown>", sid=sid)
        return hook_output("deny", reason)

    blocked: list[NormalizedPath] = []
    for raw_path in raw_paths:
        try:
            target = normalize_path(raw_path)
        except Exception:
            blocked.append(NormalizedPath(raw_path, raw_path, raw_path))
            continue
        if not any(is_within_path(target.key, boundary.key) for boundary in allowed):
            blocked.append(target)

    if blocked:
        first = blocked[0]
        reason = (
            f"Freeze active: edits are restricted to {allowed_display}. "
            f"Blocked edit outside boundary: {first.display}. "
            "Run lstack unfreeze or lstack freeze <path> to change this."
        )
        log_event(mode="freeze", action="deny", tool=tool_name, path=first.display, sid=sid)
        return hook_output("deny", reason)
    return None


def handle_hook(raw: str, sid: str | None = None) -> str | None:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    freeze_decision = freeze_hook_decision(tool_name, tool_input, sid)
    if freeze_decision:
        return freeze_decision
    if tool_name == "Bash":
        return bash_hook_decision(tool_input, sid)
    return None


def resolve_allowed_paths(paths: list[str], cwd: str | None = None) -> list[str]:
    if not paths:
        raise ValueError("at least one allowed path is required")
    return [normalize_path(path, cwd).display for path in paths]


def cmd_freeze(args: argparse.Namespace) -> int:
    sid = session_id()
    if args.clear:
        removed = clear_state("freeze", sid)
        print("Freeze cleared." if removed else "Freeze was not active.")
        return 0
    if args.show:
        print_status(show_json=args.json)
        return 0
    paths = list(args.paths or []) + list(args.allow or [])
    if not paths:
        print("Usage: lstack freeze PATH | lstack freeze --allow PATH [--allow PATH2]", file=sys.stderr)
        return 2
    try:
        allowed = resolve_allowed_paths(paths)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = {
        "active": True,
        "created_at": iso_now(),
        "session_id": sid,
        "mode": "freeze",
        "allowed_paths": allowed,
        "original_args": paths,
    }
    path = write_json_state("freeze", data, sid)
    print(f"Freeze active for session {sid}.")
    print("Edits are restricted to:")
    for allowed_path in allowed:
        print(f"  {allowed_path}")
    print("Applies to Edit, Write, and MultiEdit. Bash is not sandboxed.")
    print(f"State file: {path}")
    return 0


def cmd_safety(args: argparse.Namespace) -> int:
    sid = session_id()
    if args.safety_command == "status":
        print_status(show_json=args.json)
        return 0
    if args.safety_command == "allow-once":
        safety_state = read_json_state("safety", sid)
        data = safety_state.data if not safety_state.malformed else {}
        data.setdefault("active", True)
        data.setdefault("mode", "careful")
        data.setdefault("created_at", iso_now())
        data["session_id"] = sid
        allow_once = data.get("allow_once")
        if not isinstance(allow_once, list):
            allow_once = []
        if args.hash not in allow_once:
            allow_once.append(args.hash)
        data["allow_once"] = allow_once
        path = write_json_state("safety", data, sid)
        print(f"Allowed once for command hash: {args.hash}")
        print(f"State file: {path}")
        return 0
    if args.safety_command == "off":
        data = {
            "active": False,
            "mode": "off",
            "created_at": iso_now(),
            "session_id": sid,
        }
        path = write_json_state("safety", data, sid)
        print("Safety mode: off")
        print(f"State file: {path}")
        return 0
    mode = args.safety_command
    data = {
        "active": True,
        "mode": mode,
        "created_at": iso_now(),
        "session_id": sid,
        "allow_once": [],
    }
    path = write_json_state("safety", data, sid)
    print(f"Safety mode: {mode}")
    print(f"State file: {path}")
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    sid = session_id()
    if args.clear:
        freeze_removed = clear_state("freeze", sid)
        safety_removed = clear_state("safety", sid)
        print(
            "Guard cleared."
            if freeze_removed or safety_removed
            else "Guard was not active."
        )
        return 0
    paths = list(args.paths or []) + list(args.allow or [])
    if not paths:
        print("Usage: lstack guard PATH | lstack guard --allow PATH [--allow PATH2]", file=sys.stderr)
        return 2
    try:
        allowed = resolve_allowed_paths(paths)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    safety_mode = "strict" if args.strict else "careful"
    write_json_state(
        "safety",
        {
            "active": True,
            "mode": safety_mode,
            "created_at": iso_now(),
            "session_id": sid,
            "allow_once": [],
        },
        sid,
    )
    write_json_state(
        "freeze",
        {
            "active": True,
            "created_at": iso_now(),
            "session_id": sid,
            "mode": "guard",
            "allowed_paths": allowed,
            "original_args": paths,
        },
        sid,
    )
    print(f"Guard active for session {sid}.")
    print(f"Safety mode: {safety_mode}")
    print("Edits are restricted to:")
    for allowed_path in allowed:
        print(f"  {allowed_path}")
    print("Bash is not sandboxed; risky Bash commands are checked by careful/strict mode.")
    return 0


def recent_event_count(sid: str) -> int:
    path = events_file()
    if not path.exists():
        return 0
    safe_sid = safe_session_id(sid)
    count = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh.readlines()[-500:]:
                if f"session={safe_sid}" in line and (
                    "action=deny" in line or "action=ask" in line or "action=warn" in line
                ):
                    count += 1
    except Exception:
        return 0
    return count


def status_data() -> dict[str, Any]:
    sid = session_id()
    mode, safety_state = load_safety_mode(sid)
    freeze_state = read_json_state("freeze", sid)
    freeze_active = False
    allowed_paths: list[str] = []
    freeze_created = None
    if not freeze_state.stale and not freeze_state.malformed and freeze_is_active(freeze_state):
        freeze_active = True
        allowed_paths = [
            str(path)
            for path in freeze_state.data.get("allowed_paths", [])
            if isinstance(path, str)
        ]
        freeze_created = freeze_state.data.get("created_at")
    return {
        "session_id": sid,
        "safety_mode": mode,
        "safety_created_at": safety_state.data.get("created_at"),
        "safety_state_file": str(safety_state.path),
        "safety_state_malformed": safety_state.malformed,
        "freeze_active": freeze_active,
        "freeze_created_at": freeze_created,
        "freeze_allowed_paths": allowed_paths,
        "freeze_state_file": str(freeze_state.path),
        "freeze_state_malformed": freeze_state.malformed,
        "recent_blocked_or_warned_events": recent_event_count(sid),
    }


def print_status(show_json: bool = False) -> None:
    data = status_data()
    if show_json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    print(f"safety mode: {data['safety_mode']}")
    print(f"freeze active: {str(data['freeze_active']).lower()}")
    print("allowed paths:")
    if data["freeze_allowed_paths"]:
        for path in data["freeze_allowed_paths"]:
            print(f"  {path}")
    else:
        print("  (none)")
    print(f"session id: {data['session_id']}")
    print(f"safety created_at: {data['safety_created_at'] or '(none)'}")
    print(f"freeze created_at: {data['freeze_created_at'] or '(none)'}")
    print(f"safety state file: {data['safety_state_file']}")
    print(f"freeze state file: {data['freeze_state_file']}")
    print(f"recent blocked/warned events: {data['recent_blocked_or_warned_events']}")
    if data["safety_state_malformed"]:
        print("warning: safety state is malformed")
    if data["freeze_state_malformed"]:
        print("warning: freeze state is malformed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="safety.py")
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser("freeze")
    freeze.add_argument("paths", nargs="*")
    freeze.add_argument("--allow", action="append", default=[])
    freeze.add_argument("--show", action="store_true")
    freeze.add_argument("--clear", action="store_true")
    freeze.add_argument("--json", action="store_true")
    freeze.set_defaults(func=cmd_freeze)

    safety = sub.add_parser("safety")
    safety_sub = safety.add_subparsers(dest="safety_command", required=True)
    for mode in ("off", "careful", "strict"):
        mode_parser = safety_sub.add_parser(mode)
        mode_parser.set_defaults(func=cmd_safety)
    status = safety_sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_safety)
    allow_once = safety_sub.add_parser("allow-once")
    allow_once.add_argument("hash")
    allow_once.set_defaults(func=cmd_safety)

    guard = sub.add_parser("guard")
    guard.add_argument("paths", nargs="*")
    guard.add_argument("--allow", action="append", default=[])
    guard.add_argument("--strict", action="store_true")
    guard.add_argument("--clear", action="store_true")
    guard.set_defaults(func=cmd_guard)

    hook = sub.add_parser("hook")
    hook.set_defaults(func=lambda _args: print(handle_hook(sys.stdin.read()) or "", end=""))

    analyze = sub.add_parser("analyze")
    analyze.add_argument("command_text")
    analyze.set_defaults(
        func=lambda args: print(json.dumps(analyze_command(args.command_text), indent=2, sort_keys=True))
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
