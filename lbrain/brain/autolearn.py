"""Automatic learning policy for LBrain hook events.

Controls whether hook events are recorded, candidates created,
and safe project-scoped candidates auto-promoted.
All decisions are explainable. Never calls an LLM. Fails open.
"""

import json
import os
import sys
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────────────


def is_autolearn_enabled():
    return os.environ.get("LSTACK_BRAIN_AUTO_LEARN", "1") != "0"


def is_autopromote_enabled():
    return os.environ.get("LSTACK_BRAIN_AUTO_PROMOTE", "1") != "0"


def max_output_preview():
    try:
        return int(os.environ.get("LSTACK_BRAIN_AUTO_LEARN_MAX_OUTPUT_PREVIEW", "500"))
    except Exception:
        return 500


def max_events_per_session():
    val = os.environ.get("LSTACK_BRAIN_AUTO_LEARN_MAX_EVENTS_PER_SESSION", "")
    if val:
        try:
            return int(val)
        except Exception:
            pass
    return None


def autolearn_config():
    return {
        "auto_learn_enabled": is_autolearn_enabled(),
        "auto_promote_enabled": is_autopromote_enabled(),
        "max_output_preview": max_output_preview(),
        "max_events_per_session": max_events_per_session(),
        "debug": os.environ.get("LSTACK_BRAIN_AUTO_LEARN_DEBUG", "0") != "0",
    }


def _debug_log(msg):
    if os.environ.get("LSTACK_BRAIN_AUTO_LEARN_DEBUG", "0") != "0":
        print(f"[autolearn] {msg}", file=sys.stderr)


# ── Payload extraction ────────────────────────────────────────────────────────


def extract_command(tool_name, tool_input):
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Bash":
        cmd = tool_input.get("command") or ""
        return str(cmd)[:500]
    return None


def extract_exit_code(tool_response):
    if not isinstance(tool_response, dict):
        return None
    ec = tool_response.get("exit_code")
    if ec is not None:
        try:
            return int(ec)
        except Exception:
            pass
    # Infer failure from output when exit_code is absent
    output = str(tool_response.get("output") or "").lower()
    if any(p in output for p in ("command not found", "no such file or directory", ": error:", "failed: ")):
        return 1
    return None


def extract_output_preview(tool_response, max_chars=None):
    limit = max_chars if max_chars is not None else max_output_preview()
    if not isinstance(tool_response, dict):
        if isinstance(tool_response, str):
            return str(tool_response)[:limit]
        return None
    output = tool_response.get("output") or tool_response.get("stderr") or ""
    return str(output)[:limit]


def extract_file_path(tool_name, tool_input):
    if not isinstance(tool_input, dict):
        return None
    if tool_name in ("Write", "Edit", "MultiEdit"):
        return str(tool_input.get("file_path") or tool_input.get("path") or "")
    return None


# ── Package manager detection ─────────────────────────────────────────────────


def probe_package_manager(cwd=None):
    """Read package.json and lockfiles to detect package manager.

    Returns dict with package_manager, source, lockfile, lockfile_agrees, conflict
    or None if no evidence found.
    """
    try:
        directory = Path(cwd or os.getcwd())
        pkg_json_path = directory / "package.json"
        if not pkg_json_path.exists():
            return None
        with open(pkg_json_path, encoding="utf-8", errors="ignore") as f:
            pkg = json.load(f)
    except Exception:
        return None

    pm_name = None
    pm_version = None
    pm_field = pkg.get("packageManager", "")
    if pm_field:
        parts = str(pm_field).split("@", 1)
        candidate_pm = parts[0].strip().lower()
        if candidate_pm in ("pnpm", "npm", "yarn", "bun"):
            pm_name = candidate_pm
            pm_version = parts[1] if len(parts) > 1 else None

    lockfile_map = [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
        ("bun.lockb", "bun"),
    ]
    lockfile_pm = None
    for lockfile_name, lm in lockfile_map:
        if (directory / lockfile_name).exists():
            lockfile_pm = lm
            break

    if not pm_name and not lockfile_pm:
        return None

    agrees = (pm_name == lockfile_pm) if (pm_name and lockfile_pm) else True
    return {
        "package_manager": pm_name or lockfile_pm,
        "package_manager_version": pm_version,
        "source": "packageManager_field" if pm_name else "lockfile",
        "lockfile": lockfile_pm,
        "lockfile_agrees": agrees,
        "conflict": not agrees,
    }


# ── Rate limiting and deduplication ──────────────────────────────────────────


def _check_rate_limit(con, project_id):
    """Return True if we are within the per-session event limit."""
    limit = max_events_per_session()
    if limit is None:
        return True
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    if not session_id:
        return True
    count = con.execute(
        """
        SELECT COUNT(*) FROM brain_capture_events
        WHERE project_id = ? AND session_id = ? AND source = 'hook'
        """,
        (project_id, session_id),
    ).fetchone()[0]
    return count < limit


def _already_recorded_today(con, project_id, event_type):
    """Return True if this event type was already recorded today for this project."""
    from .db import iso_now
    today = iso_now()[:10]
    count = con.execute(
        """
        SELECT COUNT(*) FROM brain_capture_events
        WHERE project_id = ? AND event_type = ? AND created_at >= ?
        """,
        (project_id, event_type, today + "T00:00:00Z"),
    ).fetchone()[0]
    return count > 0


# ── Event classification ──────────────────────────────────────────────────────


_TEST_PATTERNS = (
    "pytest", "python -m unittest", "py -3 -m unittest",
    "jest", "vitest", "mocha", "jasmine",
    "go test", "cargo test",
    "npm test", "pnpm test", "yarn test", "bun test",
    "npx jest", "npx vitest",
)


def _looks_like_test_command(command):
    if not command:
        return False
    lower = command.lower()
    return any(p in lower for p in _TEST_PATTERNS)


def _classify_bash_events(command, exit_code, output_preview):
    """Return list of (event_type, summary, evidence) tuples for a Bash call."""
    results = []
    if not command:
        return results

    is_failure = exit_code is not None and exit_code != 0
    is_success = exit_code is not None and exit_code == 0

    if is_failure:
        results.append((
            "failed_command",
            f"Command failed (exit {exit_code}): {command[:200]}",
            {
                "exit_code": exit_code,
                "output_preview": output_preview or "",
            },
        ))

    if _looks_like_test_command(command):
        result = "pass" if is_success else ("fail" if is_failure else "unknown")
        results.append((
            "test_result",
            f"Test {'passed' if result == 'pass' else 'failed' if result == 'fail' else 'ran'}: {command[:200]}",
            {
                "test_result": result,
                "exit_code": exit_code,
                "output_preview": output_preview or "",
            },
        ))

    return results


# ── Platform and package manager event recording ──────────────────────────────


def _maybe_record_platform_detection(con, project_id, session_id):
    """Record platform_detection once per project per day if informative."""
    if _already_recorded_today(con, project_id, "platform_detection"):
        return None
    try:
        from .platform import platform_facts
        facts = platform_facts()
        os_name = facts.get("os", "")
        shell_mode = facts.get("shell_mode", "")
        if not (os_name and shell_mode):
            return None
        summary = f"Platform detected: {os_name} / {shell_mode}"
        from .capture import record_event
        result = record_event(
            con,
            project_id,
            event_type="platform_detection",
            summary=summary,
            source="hook",
            session_id=session_id,
            evidence={
                "os": os_name,
                "shell_mode": shell_mode,
                "is_wsl": facts.get("is_wsl", False),
            },
            allow_auto_promote=is_autopromote_enabled(),
        )
        _debug_log(f"platform_detection: event {result['event']['id'] if result.get('event') else None}")
        return result
    except Exception as exc:
        _debug_log(f"platform detection error: {exc}")
        return None


def _maybe_record_package_manager(con, project_id, session_id, cwd=None):
    """Record package_manager_detection once per project per day if unambiguous."""
    if _already_recorded_today(con, project_id, "package_manager_detection"):
        return None
    pm_info = probe_package_manager(cwd)
    if not pm_info:
        return None
    pm = pm_info["package_manager"]
    conflict = pm_info.get("conflict", False)
    if conflict:
        _debug_log(f"package manager conflict detected: {pm_info}, staying pending")
    summary = f"Package manager detected: {pm} (source={pm_info['source']})"
    try:
        from .capture import record_event
        result = record_event(
            con,
            project_id,
            event_type="package_manager_detection",
            summary=summary,
            source="hook",
            session_id=session_id,
            evidence=pm_info,
            # Only auto-promote if no conflict and auto-promote enabled
            allow_auto_promote=is_autopromote_enabled() and not conflict,
        )
        _debug_log(f"package_manager_detection: event {result['event']['id'] if result.get('event') else None}")
        return result
    except Exception as exc:
        _debug_log(f"package manager detection error: {exc}")
        return None


def _maybe_attach_receipt(con, project, result, tool_name=None, file_path=None):
    """Best-effort receipt attachment for hook-created capture events."""
    try:
        if not result or not result.get("event"):
            return None
        from .receipts import attach_hook_event
        event_id = result["event"]["id"]
        return attach_hook_event(con, project, event_id, tool_name=tool_name, file_path=file_path)
    except Exception as exc:
        _debug_log(f"receipt attach skipped: {exc}")
        return None


# ── Core processing ───────────────────────────────────────────────────────────


def process_hook_payload(payload, cwd=None):
    """Process a hook JSON payload and record auto-learn events.

    Always returns a dict. Never raises. Callers should fail open.
    """
    if not is_autolearn_enabled():
        _debug_log("auto-learn disabled")
        return {"status": "disabled"}

    if not isinstance(payload, dict):
        return {"status": "invalid"}

    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    session_id = os.environ.get("CLAUDE_SESSION_ID") or None

    command = extract_command(tool_name, tool_input)
    exit_code = extract_exit_code(tool_response)
    output_preview = extract_output_preview(tool_response)
    file_path = extract_file_path(tool_name, tool_input)

    _debug_log(f"tool={tool_name} exit_code={exit_code} cmd={repr((command or '')[:60])}")

    try:
        from .db import connect, ensure_project
        from pathlib import Path as _Path
        _db_env = os.environ.get("LSTACK_DB_PATH")
        con = connect(_Path(_db_env)) if _db_env else connect()
    except Exception as exc:
        _debug_log(f"DB connect error: {exc}")
        return {"status": "db_error", "error": str(exc)}

    try:
        effective_cwd = cwd or os.getcwd()
        project = ensure_project(con, cwd=effective_cwd)
    except Exception as exc:
        _debug_log(f"ensure_project error: {exc}")
        try:
            con.close()
        except Exception:
            pass
        return {"status": "project_error", "error": str(exc)}

    project_id = project["id"]

    try:
        if not _check_rate_limit(con, project_id):
            _debug_log("rate limited")
            return {"status": "rate_limited"}

        results = []

        # Once-per-day ambient signals
        ambient = _maybe_record_platform_detection(con, project_id, session_id)
        _maybe_attach_receipt(con, project, ambient, tool_name=tool_name, file_path=file_path)
        ambient = _maybe_record_package_manager(con, project_id, session_id, cwd=effective_cwd)
        _maybe_attach_receipt(con, project, ambient, tool_name=tool_name, file_path=file_path)

        # Bash tool events
        if tool_name == "Bash":
            for event_type, summary, evidence in _classify_bash_events(command, exit_code, output_preview):
                try:
                    from .capture import record_event
                    result = record_event(
                        con,
                        project_id,
                        event_type=event_type,
                        summary=summary,
                        source="hook",
                        command=command,
                        session_id=session_id,
                        evidence=evidence,
                        allow_auto_promote=is_autopromote_enabled(),
                    )
                    results.append(result)
                    _maybe_attach_receipt(con, project, result, tool_name=tool_name, file_path=file_path)
                    _debug_log(
                        f"recorded {event_type}: event={result['event']['id']}"
                        + (f" candidate={result['candidate']['id']}" if result.get("candidate") else "")
                    )
                except Exception as exc:
                    _debug_log(f"record_event error ({event_type}): {exc}")

        # File tool events
        elif tool_name in ("Write", "Edit", "MultiEdit") and file_path:
            try:
                from .capture import record_event
                result = record_event(
                    con,
                    project_id,
                    event_type="implementation_diff",
                    summary=f"File modified: {file_path}",
                    source="hook",
                    path=file_path,
                    session_id=session_id,
                    evidence={"tool_name": tool_name},
                    allow_auto_promote=is_autopromote_enabled(),
                )
                results.append(result)
                _maybe_attach_receipt(con, project, result, tool_name=tool_name, file_path=file_path)
                _debug_log(f"recorded implementation_diff: event={result['event']['id']}")
            except Exception as exc:
                _debug_log(f"record_event error (implementation_diff): {exc}")

        return {"status": "ok", "results": results, "project_id": project_id}

    except Exception as exc:
        _debug_log(f"processing error: {exc}")
        return {"status": "error", "error": str(exc)}
    finally:
        try:
            con.close()
        except Exception:
            pass
