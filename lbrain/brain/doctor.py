"""Doctor checks for LBrain."""

import json

from .db import DB_PATH, connect
from .decisions import check_decisions
from .passport import detect_passport
from .platform import normalize_path, path_warnings, platform_facts
from .project import is_lstack_project, lstack_project_signals, project_info
from .redaction import redact_text
from .schema import missing_phase_1a_tables, missing_phase_1b_tables


def run_doctor(db_path=None):
    checks = []

    def add(check_id, status, message):
        checks.append({"id": check_id, "status": status, "message": message})

    try:
        con = connect(db_path or DB_PATH, initialize=False, create=False)
        add("db.reachable", "pass", "DB reachable")
    except Exception as exc:
        return {"status": "fail", "checks": [{"id": "db.reachable", "status": "fail", "message": str(exc)}]}

    missing_1a = missing_phase_1a_tables(con)
    missing_1b = missing_phase_1b_tables(con)
    if missing_1a:
        add(
            "schema.tables",
            "fail",
            "Missing tables: "
            + ", ".join(missing_1a)
            + ". Run: lstack brain status to initialize Phase 1A tables safely.",
        )
    else:
        add("schema.tables", "pass", "Phase 1A tables exist")

    if missing_1b:
        add(
            "schema.phase1b",
            "fail",
            "Missing Phase 1B tables: "
            + ", ".join(missing_1b)
            + ". Run: lstack brain status to initialize LBrain tables safely.",
        )
    else:
        add("schema.phase1b", "pass", "Phase 1B capture and decisions tables exist")

    facts = platform_facts()
    add("platform.mode", "pass", f"Platform: {facts['os']}; shell mode: {facts['shell_mode']}")
    if facts.get("is_wsl"):
        add(
            "platform.wsl",
            "warn",
            "WSL detected. Windows-specific lstack behavior targets Git Bash, not WSL.",
        )
    else:
        add("platform.wsl", "pass", "WSL not detected")

    try:
        project = project_info()
        add("project.detectable", "pass", f"Project detected: {project['name']}")
        signals = lstack_project_signals(project)
        if is_lstack_project(project):
            add("project.lstack_repo", "pass", "Current project matches lstack signals: " + ", ".join(signals[:5]))
        else:
            add("project.lstack_repo", "pass", "Current project is not treated as the lstack repo")
    except Exception as exc:
        project = None
        add("project.detectable", "fail", f"Project detection failed: {exc}")

    project_id = None
    if project and not missing_1a:
        try:
            row = con.execute(
                "SELECT id FROM brain_projects WHERE root_path_hash = ?",
                (project["root_path_hash"],),
            ).fetchone()
            project_id = row["id"] if row else None
            if project_id:
                latest_passport = con.execute(
                    "SELECT COUNT(*) FROM brain_passports WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0]
                attempts = con.execute(
                    "SELECT COUNT(*) FROM brain_attempts WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0]
                context_decisions = con.execute(
                    "SELECT COUNT(*) FROM brain_context_decisions WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0]
                add("project.latest_passport", "pass", f"Latest passport: {'yes' if latest_passport else 'no'}")
                add("project.attempts", "pass", f"Attempts for current project: {attempts}")
                add("project.context_decisions", "pass", f"Context decisions for current project: {context_decisions}")
            else:
                add("project.latest_passport", "warn", "Current project is not initialized in LBrain DB yet")
                add("project.attempts", "warn", "Current project is not initialized in LBrain DB yet")
                add("project.context_decisions", "warn", "Current project is not initialized in LBrain DB yet")
        except Exception:
            project_id = None

    if project:
        try:
            detected = detect_passport(project["root"], {**project, "id": 0})
            add("passport.generate", "pass", "Passport can be generated")
            json.dumps(detected)
            add("json.output", "pass", "JSON output works")
        except Exception as exc:
            add("passport.generate", "fail", f"Passport generation failed: {exc}")

    if not missing_1b and project_id:
        project_for_check = {**project, "id": project_id}
        active_decisions = con.execute(
            "SELECT COUNT(*) FROM brain_decisions WHERE project_id = ? AND scope = 'project' AND status = 'active'",
            (project_id,),
        ).fetchone()[0]
        pending_candidates = con.execute(
            "SELECT COUNT(*) FROM brain_memory_candidates WHERE project_id = ? AND scope = 'project' AND status = 'pending'",
            (project_id,),
        ).fetchone()[0]
        rejected_stale = con.execute(
            """
            SELECT COUNT(*) FROM brain_memory_candidates
            WHERE project_id = ? AND scope = 'project' AND status IN ('rejected', 'stale')
            """,
            (project_id,),
        ).fetchone()[0]
        add("decisions.active_count", "pass", f"Active decisions: {active_decisions}")
        add("capture.pending_candidates", "pass", f"Pending candidates: {pending_candidates}")
        add("capture.rejected_stale", "pass", f"Rejected or stale candidates: {rejected_stale}")
        try:
            decision_check = check_decisions(con, project_for_check, record_regressions=False)
            violations = decision_check.get("violation_count", 0)
            status = "warn" if violations else "pass"
            add("decisions.check", status, f"Decision violations: {violations}")
            add("decisions.scan", "pass", f"Decision check scanned {len(decision_check.get('checked_files', []))} file(s)")
        except Exception as exc:
            add("decisions.check", "fail", f"Decision check failed: {exc}")
        if active_decisions:
            add("context.decisions", "pass", "Active decisions are available for context export")
        else:
            add("context.decisions", "warn", "No active decisions available for context export")
    elif not missing_1b:
        add("decisions.active_count", "warn", "Project is not initialized in LBrain DB yet")
        add("capture.pending_candidates", "warn", "Project is not initialized in LBrain DB yet")

    redacted, status = redact_text("Authorization: Bearer abc.def.ghi\nAPI_KEY=abc123")
    if status == "redacted" and "<redacted>" in redacted:
        add("redaction.basic", "pass", "Redaction works on test secret")
    else:
        add("redaction.basic", "fail", "Redaction did not redact test secret")

    if normalize_path("/d/Work Space/repo") == "D:/Work Space/repo":
        add("paths.windows_git_bash", "pass", "Windows Git Bash path normalization works")
    else:
        add("paths.windows_git_bash", "fail", "Windows Git Bash path normalization failed")

    if path_warnings("/mnt/c/Users/Name/repo", "git-bash"):
        add("paths.wsl_warning", "pass", "WSL path warning works in Git Bash mode")
    else:
        add("paths.wsl_warning", "fail", "WSL path warning missing")

    add("cloud.optional", "pass", "No cloud dependency required")
    add("embeddings.optional", "pass", "Embeddings are not required")
    add("hooks.capture", "warn", "Hook capture integration is not enabled in Phase 1B; use lstack brain capture event for safe manual capture.")

    con.close()
    status_order = {"pass": 0, "warn": 1, "fail": 2}
    overall = max((c["status"] for c in checks), key=lambda s: status_order[s])
    return {"status": overall, "checks": checks}


def render_doctor(result):
    lines = ["LBrain doctor"]
    for check in result["checks"]:
        marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[check["status"]]
        lines.append(f"{marker} {check['id']}: {check['message']}")
    lines.append(f"Status: {result['status']}")
    return "\n".join(lines)
