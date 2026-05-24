"""Doctor checks for LBrain."""

import json
from pathlib import Path

from .autolearn import autolearn_config
from .db import DB_PATH, connect
from .decisions import check_decisions
from .passport import detect_passport
from .platform import normalize_path, path_warnings, platform_facts
from .project import is_lstack_project, lstack_project_signals, project_info
from .redaction import redact_text
from .schema import missing_phase_1a_tables, missing_phase_1b_tables, missing_phase_1c_tables


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
    missing_1c = missing_phase_1c_tables(con)
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

    if missing_1c:
        add(
            "schema.phase1c",
            "fail",
            "Missing Phase 1C tables: "
            + ", ".join(missing_1c)
            + ". Run: lstack brain status to initialize LBrain tables safely.",
        )
    else:
        add("schema.phase1c", "pass", "Phase 1C contract tables exist")

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

    if not missing_1c and project_id:
        try:
            active_contracts = con.execute(
                "SELECT COUNT(*) FROM brain_contracts WHERE project_id = ? AND status = 'active'",
                (project_id,),
            ).fetchone()[0]
            if active_contracts:
                row = con.execute(
                    "SELECT id, mode, violation_count, required_tests_json, recorded_tests_json "
                    "FROM brain_contracts WHERE project_id = ? AND status = 'active' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (project_id,),
                ).fetchone()
                try:
                    required_count = len(json.loads(row["required_tests_json"] or "[]"))
                    recorded_count = len(json.loads(row["recorded_tests_json"] or "[]"))
                except Exception:
                    required_count = 0
                    recorded_count = 0
                add(
                    "contracts.active",
                    "pass",
                    f"Active contract #{row['id']}: mode={row['mode']}, "
                    f"violations={row['violation_count']}, "
                    f"required_tests={required_count}, recorded_tests={recorded_count}",
                )
                if row["violation_count"] > 0:
                    add("contracts.violations", "warn", f"Active contract has {row['violation_count']} violation(s)")
                else:
                    add("contracts.violations", "pass", "Active contract has no violations")
            else:
                add("contracts.active", "pass", "No active contract (not required)")
                add("contracts.violations", "pass", "No active contract to check")
            add("contracts.check", "pass", "Contract check is available via: lstack brain contract check")
        except Exception as exc:
            add("contracts.active", "fail", f"Contract check failed: {exc}")
    elif not missing_1c:
        add("contracts.active", "warn", "Project not initialized in LBrain DB yet")
    else:
        add("contracts.active", "warn", "Phase 1C tables not yet initialized")

    add("cloud.optional", "pass", "No cloud dependency required")
    add("embeddings.optional", "pass", "Embeddings are not required")

    # Auto-learn health
    al = autolearn_config()
    add(
        "autolearn.enabled",
        "pass" if al["auto_learn_enabled"] else "warn",
        f"Automatic learning: {'enabled' if al['auto_learn_enabled'] else 'disabled (LSTACK_BRAIN_AUTO_LEARN=0)'}",
    )
    add(
        "autolearn.promote",
        "pass" if al["auto_promote_enabled"] else "warn",
        f"Automatic promotion: {'enabled' if al['auto_promote_enabled'] else 'disabled (LSTACK_BRAIN_AUTO_PROMOTE=0)'}",
    )

    hook_wrapper = Path.home() / ".claude" / "scripts" / "lbrain-capture-hook.py"
    if hook_wrapper.exists():
        add("autolearn.hook_wrapper", "pass", "Hook wrapper exists: scripts/lbrain-capture-hook.py")
    else:
        add("autolearn.hook_wrapper", "warn", "Hook wrapper not found: scripts/lbrain-capture-hook.py")

    # Check PostToolUse Bash matcher in settings.json
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
            post_tool_hooks = settings_data.get("hooks", {}).get("PostToolUse", [])
            bash_in_matcher = any("Bash" in str(h.get("matcher") or "") for h in post_tool_hooks)
            if bash_in_matcher:
                add("autolearn.posttooluse_bash", "pass", "PostToolUse hook includes Bash matcher")
            else:
                add(
                    "autolearn.posttooluse_bash",
                    "warn",
                    "PostToolUse hook does not include Bash; failed-command capture will not fire. Run: lstack gen-settings",
                )
        except Exception:
            add("autolearn.posttooluse_bash", "warn", "Could not read settings.json; run: lstack gen-settings")
    else:
        add("autolearn.posttooluse_bash", "warn", "settings.json not found; run: lstack gen-settings")

    if project_id and not missing_1b:
        hook_event_count = con.execute(
            "SELECT COUNT(*) FROM brain_capture_events WHERE project_id = ? AND source = 'hook'",
            (project_id,),
        ).fetchone()[0]
        add("autolearn.hook_events", "pass", f"Auto-captured events (hook source): {hook_event_count}")

        promoted_decisions = con.execute(
            """
            SELECT COUNT(*) FROM brain_memory_candidates
            WHERE project_id = ? AND status = 'promoted' AND promoted_to_type = 'brain_decisions'
            """,
            (project_id,),
        ).fetchone()[0]
        promoted_attempts = con.execute(
            """
            SELECT COUNT(*) FROM brain_memory_candidates
            WHERE project_id = ? AND status = 'promoted' AND promoted_to_type = 'brain_attempts'
            """,
            (project_id,),
        ).fetchone()[0]
        add(
            "autolearn.promoted",
            "pass",
            f"Auto-promoted decisions: {promoted_decisions}, attempts: {promoted_attempts}",
        )
    elif not missing_1b:
        add("autolearn.hook_events", "warn", "Project not initialized in LBrain DB yet")
        add("autolearn.promoted", "warn", "Project not initialized in LBrain DB yet")

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
