"""LStack-wide dashboard overview builder."""

import datetime
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from .schemas import SCHEMA_VERSION, DASHBOARD_VERSION
from .security import clamp, redact

CLAUDE_DIR = Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))
DB_PATH = Path(os.environ.get("LSTACK_DB_PATH", CLAUDE_DIR / "memory" / "lstack.db"))
SKILLS_DIR = CLAUDE_DIR / "skills"
AGENTS_DIR = CLAUDE_DIR / "agents"
HOOKS_DIR = CLAUDE_DIR / "hooks"
PARALLEL_DIR = CLAUDE_DIR / "parallel"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:
        msg = clamp(str(exc), 120)
        return {"available": False, "error": msg} if default is None else default


def _git(*args, cwd=None) -> str:
    try:
        r = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=5,
            cwd=str(cwd or CLAUDE_DIR),
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _hook_syntax(p: Path) -> str:
    if not p.exists():
        return "unknown"
    try:
        r = subprocess.run(["bash", "-n", str(p)], capture_output=True, timeout=5)
        return "pass" if r.returncode == 0 else "fail"
    except FileNotFoundError:
        return "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_project() -> dict:
    def _inner():
        return {
            "name": CLAUDE_DIR.name,
            "root_path_display": str(CLAUDE_DIR),
            "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        }
    return _safe(_inner, {"name": "unknown", "root_path_display": str(CLAUDE_DIR), "git_branch": "unknown"})


def build_runtime() -> dict:
    def _inner():
        import platform as _pl
        os_name = _pl.system().lower()
        os_label = {"windows": "windows", "darwin": "macos"}.get(os_name, "linux")
        shell_mode = os.environ.get("LSTACK_SHELL_MODE", "")
        if not shell_mode:
            if os.environ.get("MSYSTEM"):
                shell_mode = "git-bash"
            elif os.environ.get("WSL_DISTRO_NAME"):
                shell_mode = "wsl"
            elif os_label == "windows":
                shell_mode = "cmd"
            else:
                shell_mode = "posix"
        py_provider = "python3"
        if os_label == "windows":
            try:
                r = subprocess.run(["py", "-3", "--version"], capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    py_provider = "py-launcher"
            except Exception:
                pass
        path_rule = {"git-bash": "msys2", "wsl": "wsl", "cmd": "windows"}.get(shell_mode, "posix")
        return {
            "os": os_label,
            "shell_mode": shell_mode,
            "python_available": True,
            "python_provider": py_provider,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "git_available": bool(_git("--version")),
            "path_rule": path_rule,
        }
    return _safe(_inner, {"os": "unknown", "shell_mode": "unknown",
                          "python_available": True, "python_provider": "python3",
                          "git_available": False, "path_rule": "unknown"})


def build_install() -> dict:
    def _inner():
        settings_exists = SETTINGS_PATH.exists()
        settings_valid = False
        if settings_exists:
            try:
                json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                settings_valid = True
            except Exception:
                pass
        return {
            "claude_dir": str(CLAUDE_DIR),
            "settings_exists": settings_exists,
            "settings_valid_json": settings_valid,
            "version": DASHBOARD_VERSION,
        }
    return _safe(_inner, {"claude_dir": str(CLAUDE_DIR), "settings_exists": False,
                          "settings_valid_json": False, "version": DASHBOARD_VERSION})


def build_hooks() -> dict:
    def _inner():
        hooks = {
            "session_start": "session-start.sh",
            "pre_tool": "pre-tool.sh",
            "post_tool": "post-tool.sh",
            "pre_compact": "pre-compact.sh",
            "stop": "stop.sh",
        }
        result = {}
        for key, fname in hooks.items():
            p = HOOKS_DIR / fname
            result[key] = {"exists": p.exists(), "syntax": _hook_syntax(p)}
        sl = CLAUDE_DIR / "scripts" / "statusline.sh"
        result["statusline"] = {"exists": sl.exists()}
        return result
    return _safe(_inner, {})


def build_skills() -> dict:
    def _inner():
        if not SKILLS_DIR.exists():
            return {"count": 0, "items": []}
        items = sorted(d.name for d in SKILLS_DIR.iterdir()
                       if d.is_dir() and (d / "SKILL.md").exists())
        return {"count": len(items), "items": items}
    return _safe(_inner, {"count": 0, "items": []})


def build_agents() -> dict:
    def _inner():
        if not AGENTS_DIR.exists():
            return {"count": 0, "items": []}
        items = sorted(d.name for d in AGENTS_DIR.iterdir()
                       if d.is_dir() or d.suffix == ".md")
        return {"count": len(items), "items": items}
    return _safe(_inner, {"count": 0, "items": []})


def build_memory() -> dict:
    def _inner():
        if not DB_PATH.exists():
            return {"db_reachable": False, "observations_count": 0,
                    "learnings_count": 0, "fts_available": False, "semantic_available": False}
        con = sqlite3.connect(str(DB_PATH))
        try:
            obs = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        except Exception:
            obs = 0
        try:
            lrn = con.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        except Exception:
            lrn = 0
        fts = _table_exists(con, "observations_fts")
        sem = _table_exists(con, "observation_embeddings")
        con.close()
        return {"db_reachable": True, "observations_count": obs,
                "learnings_count": lrn, "fts_available": fts, "semantic_available": sem}
    return _safe(_inner, {"db_reachable": False, "observations_count": 0,
                          "learnings_count": 0, "fts_available": False, "semantic_available": False})


def _split_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def _memory_scope(project: str | None) -> str:
    if project == "global":
        return "global"
    current = str(CLAUDE_DIR.resolve()).replace("\\", "/")
    candidate = (project or "").replace("\\", "/")
    return "project" if candidate == current else "other"


def _safe_memory_text(value: str | None) -> str:
    return redact(clamp(value or "", 4096)) or ""


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def build_memory_detail(limit: int = 100) -> dict:
    """Return recent individual memory rows for the dashboard, without mutating DB state."""
    def _inner():
        base = build_memory()
        if not DB_PATH.exists():
            return {
                "available": False,
                **base,
                "observations": [],
                "learnings": [],
            }

        limit_clamped = max(1, min(int(limit or 100), 200))
        con = sqlite3.connect(str(DB_PATH))
        con.row_factory = sqlite3.Row
        observations = []
        learnings = []

        if _table_exists(con, "observations"):
            rows = con.execute(
                """
                SELECT id, session_id, project, content, tags, created_at
                FROM observations
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit_clamped,),
            ).fetchall()
            observations = [
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "project": row["project"],
                    "scope": _memory_scope(row["project"]),
                    "content": _safe_memory_text(row["content"]),
                    "tags": _split_tags(row["tags"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

        if _table_exists(con, "learnings"):
            rows = con.execute(
                """
                SELECT id, session_id, project, key, type, insight, confidence,
                       source, trusted, tags, files_json, branch, commit_sha,
                       supersedes_id, created_at, updated_at
                FROM learnings
                ORDER BY updated_at DESC, created_at DESC, id DESC
                LIMIT ?
                """,
                (limit_clamped,),
            ).fetchall()
            learnings = [
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "project": row["project"],
                    "scope": _memory_scope(row["project"]),
                    "key": row["key"],
                    "type": row["type"],
                    "insight": _safe_memory_text(row["insight"]),
                    "confidence": row["confidence"],
                    "source": row["source"],
                    "trusted": bool(row["trusted"]),
                    "tags": _split_tags(row["tags"]),
                    "files": _json_list(row["files_json"]),
                    "branch": row["branch"],
                    "commit_sha": row["commit_sha"],
                    "supersedes_id": row["supersedes_id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

        con.close()
        return {
            "available": True,
            **base,
            "observations": observations,
            "learnings": learnings,
            "limit": limit_clamped,
        }

    return _safe(_inner, {
        "available": False,
        "db_reachable": False,
        "observations_count": 0,
        "learnings_count": 0,
        "fts_available": False,
        "semantic_available": False,
        "observations": [],
        "learnings": [],
        "limit": limit,
    })


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {table} LIMIT 1")
        return True
    except Exception:
        return False


def build_health() -> dict:
    return {
        "available": True,
        "latest_saved": None,
        "note": "Health checks are not run automatically by the dashboard.",
    }


def build_parallel() -> dict:
    def _inner():
        if not PARALLEL_DIR.exists():
            return {"available": True, "legacy_command": "lstack dashboard --parallel",
                    "active": 0, "done": 0, "failed": 0, "worktrees": []}
        active = done = failed = 0
        worktrees = []
        for d in sorted(PARALLEL_DIR.iterdir()):
            if not d.is_dir() or not d.name.startswith("agent-"):
                continue
            result_file = d / "result.md"
            if not result_file.exists():
                status = "running"; active += 1
            else:
                last = ""
                try:
                    lines = result_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    last = lines[-1].upper() if lines else ""
                except Exception:
                    pass
                if "DONE" in last:
                    status = "done"; done += 1
                elif "ERROR" in last or "FAILED" in last:
                    status = "failed"; failed += 1
                else:
                    status = "unknown"
            branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=d)
            worktrees.append({"name": d.name, "branch": branch or "unknown", "status": status})
        return {"available": True, "legacy_command": "lstack dashboard --parallel",
                "active": active, "done": done, "failed": failed, "worktrees": worktrees}
    return _safe(_inner, {"available": True, "legacy_command": "lstack dashboard --parallel",
                          "active": 0, "done": 0, "failed": 0, "worktrees": []})


def build_lbrain() -> dict:
    def _inner():
        sys.path.insert(0, str(CLAUDE_DIR))
        from lbrain.brain.db import connect, ensure_project
        from lbrain.brain.overview import build_overview
        con = connect()
        project = ensure_project(con)
        data = build_overview(con, project, target="claude")
        con.close()
        return data
    return _safe(_inner)


def build_doctor() -> dict:
    def _inner():
        sys.path.insert(0, str(CLAUDE_DIR))
        from lbrain.brain.doctor import run_doctor
        dr = run_doctor()
        checks = dr.get("checks", [])
        return {
            "status": dr.get("status", "warn"),
            "warnings": [c["id"] for c in checks if c.get("status") == "warn"],
            "failures": [c["id"] for c in checks if c.get("status") == "fail"],
        }
    return _safe(_inner, {"status": "unknown", "warnings": [], "failures": []})


def build_dashboard_overview() -> dict:
    """Build the complete LStack-wide dashboard overview JSON."""
    from .actions import build_action_registry
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "read_only": True,
        "project": build_project(),
        "runtime": build_runtime(),
        "install": build_install(),
        "hooks": build_hooks(),
        "skills": build_skills(),
        "agents": build_agents(),
        "memory": build_memory(),
        "health": build_health(),
        "parallel": build_parallel(),
        "lbrain": build_lbrain(),
        "doctor": build_doctor(),
        "actions": build_action_registry(),
    }
