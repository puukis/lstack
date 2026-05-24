"""Persistent implementation decisions for LBrain."""

import fnmatch
import json
import re
from pathlib import Path

from .db import dumps, iso_now, loads
from .project import is_lstack_project
from .redaction import combine_status, redact_json, redact_text

DECISION_STATUSES = {"active", "superseded", "disabled"}
DECISION_SCOPES = {"project", "user-global", "template", "test-fixture"}
EXPLICIT_USER_SOURCES = {"manual", "user", "user-correction"}
LSTACK_SPECIFIC_DECISION_KEYS = {
    "runtime-python-provider",
    "no-claude-in-hooks",
    "stop-timeout-at-least-90",
    "do-not-use-direct-python-in-hooks",
    "keep-lbrain-included-in-packaging",
}
GENERATED_FOLDERS = {
    ".git",
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


def _clamp_confidence(value):
    try:
        confidence = int(value)
    except Exception as exc:
        raise ValueError("confidence must be an integer from 1 to 10") from exc
    if confidence < 1 or confidence > 10:
        raise ValueError("confidence must be from 1 to 10")
    return confidence


def _validate_status(status):
    if status not in DECISION_STATUSES:
        raise ValueError(f"invalid decision status: {status}")
    return status


def _validate_scope(scope, project_id, source, status):
    scope = scope or "project"
    if scope not in DECISION_SCOPES:
        raise ValueError(f"invalid decision scope: {scope}")
    if scope == "project" and project_id is None:
        raise ValueError("project-scoped decisions require a project_id")
    if scope == "user-global":
        if source not in EXPLICIT_USER_SOURCES:
            raise ValueError("user-global decisions require explicit user source")
        project_id = None
    if scope in ("template", "test-fixture") and status == "active":
        status = "disabled"
    return scope, project_id, status


def _project_key_clause(project_id):
    if project_id is None:
        return "project_id IS NULL", ()
    return "project_id = ?", (project_id,)


def _redact_list(values):
    items = []
    statuses = []
    for value in values or []:
        text, status = redact_text(value, max_length=500)
        if text:
            items.append(text)
        statuses.append(status)
    return items, combine_status(*statuses)


def decision_row_to_dict(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "scope": row["scope"],
        "key": row["key"],
        "title": row["title"],
        "decision": row["decision"],
        "rationale": row["rationale"],
        "enforcement_hint": row["enforcement_hint"],
        "applies_to": loads(row["applies_to_json"], []),
        "forbidden_patterns": loads(row["forbidden_patterns_json"], []),
        "required_patterns": loads(row["required_patterns_json"], []),
        "evidence": loads(row["evidence_json"], {}),
        "source": row["source"],
        "confidence": row["confidence"],
        "status": row["status"],
        "privacy_class": row["privacy_class"],
        "redaction_status": row["redaction_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "supersedes_key": row["supersedes_key"],
    }


def add_decision(
    con,
    project_id,
    key,
    title,
    decision,
    rationale=None,
    enforcement_hint=None,
    applies_to=None,
    forbidden_patterns=None,
    required_patterns=None,
    evidence=None,
    source="manual",
    confidence=8,
    status="active",
    privacy_class="local-only",
    supersedes_key=None,
    scope="project",
):
    key_redacted, s_key = redact_text(key, max_length=120)
    title_redacted, s_title = redact_text(title, max_length=300)
    decision_redacted, s_decision = redact_text(decision, max_length=1000)
    rationale_redacted, s_rationale = redact_text(rationale, max_length=1000)
    hint_redacted, s_hint = redact_text(enforcement_hint, max_length=1000)
    applies_redacted, s_applies = _redact_list(applies_to or [])
    forbidden_redacted, s_forbidden = _redact_list(forbidden_patterns or [])
    required_redacted, s_required = _redact_list(required_patterns or [])
    evidence_redacted, s_evidence = redact_json(evidence or {}, max_string_length=800)
    redaction_status = combine_status(
        s_key,
        s_title,
        s_decision,
        s_rationale,
        s_hint,
        s_applies,
        s_forbidden,
        s_required,
        s_evidence,
    )
    if not key_redacted or not title_redacted or not decision_redacted:
        raise ValueError("key, title, and decision are required")
    confidence = _clamp_confidence(confidence)
    status = _validate_status(status)
    scope, project_id, status = _validate_scope(scope, project_id, source, status)
    now = iso_now()

    project_clause, project_params = _project_key_clause(project_id)
    existing = con.execute(
        f"SELECT id, created_at FROM brain_decisions WHERE {project_clause} AND scope = ? AND key = ?",
        (*project_params, scope, key_redacted),
    ).fetchone()
    if existing:
        con.execute(
            """
            UPDATE brain_decisions
            SET project_id = ?, scope = ?, title = ?, decision = ?, rationale = ?, enforcement_hint = ?,
                applies_to_json = ?, forbidden_patterns_json = ?,
                required_patterns_json = ?, evidence_json = ?, source = ?,
                confidence = ?, status = ?, privacy_class = ?,
                redaction_status = ?, updated_at = ?, supersedes_key = ?
            WHERE id = ?
            """,
            (
                project_id,
                scope,
                title_redacted,
                decision_redacted,
                rationale_redacted,
                hint_redacted,
                dumps(applies_redacted),
                dumps(forbidden_redacted),
                dumps(required_redacted),
                dumps(evidence_redacted),
                source,
                confidence,
                status,
                privacy_class,
                redaction_status,
                now,
                supersedes_key,
                existing["id"],
            ),
        )
        decision_id = existing["id"]
    else:
        cur = con.execute(
            """
            INSERT INTO brain_decisions (
                project_id, scope, key, title, decision, rationale, enforcement_hint,
                applies_to_json, forbidden_patterns_json, required_patterns_json,
                evidence_json, source, confidence, status, privacy_class,
                redaction_status, created_at, updated_at, supersedes_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                scope,
                key_redacted,
                title_redacted,
                decision_redacted,
                rationale_redacted,
                hint_redacted,
                dumps(applies_redacted),
                dumps(forbidden_redacted),
                dumps(required_redacted),
                dumps(evidence_redacted),
                source,
                confidence,
                status,
                privacy_class,
                redaction_status,
                now,
                now,
                supersedes_key,
            ),
        )
        decision_id = cur.lastrowid
    con.commit()
    return get_decision(con, project_id, key_redacted, scope=scope)


def get_decision(con, project_id, key, scope="project"):
    project_clause, project_params = _project_key_clause(project_id)
    row = con.execute(
        f"SELECT * FROM brain_decisions WHERE {project_clause} AND scope = ? AND key = ?",
        (*project_params, scope, key),
    ).fetchone()
    return decision_row_to_dict(row) if row else None


def list_decisions(con, project_id, status=None, limit=50, scope="project"):
    project_clause, project_params = _project_key_clause(project_id)
    params = [*project_params, scope]
    where = f"{project_clause} AND scope = ?"
    if status:
        where += " AND status = ?"
        params.append(status)
    rows = con.execute(
        f"""
        SELECT * FROM brain_decisions
        WHERE {where}
        ORDER BY status = 'active' DESC, confidence DESC, updated_at DESC, id DESC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()
    return [decision_row_to_dict(row) for row in rows]


def is_lstack_specific_decision(decision):
    if decision.get("key") in LSTACK_SPECIFIC_DECISION_KEYS:
        return True
    text = " ".join(
        str(decision.get(field) or "").lower()
        for field in ("title", "decision", "rationale", "enforcement_hint")
    )
    return "lstack" in text and any(word in text for word in ("runtime", "hook", "packaging"))


def list_context_decisions(con, project, limit=8):
    project_items = list_decisions(con, project["id"], status="active", limit=limit, scope="project")
    current_is_lstack = is_lstack_project(project)
    included = []
    skipped = []
    for item in project_items:
        if (
            is_lstack_specific_decision(item)
            and not current_is_lstack
            and item.get("source") not in EXPLICIT_USER_SOURCES
        ):
            skipped.append({**item, "skip_reason": "lstack-specific detected decision is not active outside the lstack repo"})
            continue
        included.append(item)

    remaining = max(0, limit - len(included))
    if remaining:
        rows = con.execute(
            """
            SELECT * FROM brain_decisions
            WHERE project_id IS NULL
              AND scope = 'user-global'
              AND status = 'active'
              AND source IN ('manual', 'user', 'user-correction')
            ORDER BY confidence DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (remaining,),
        ).fetchall()
        included.extend(decision_row_to_dict(row) for row in rows)
    return included, skipped


def search_decisions(con, project_id, query, limit=20, scope="project"):
    like = f"%{query}%"
    project_clause, project_params = _project_key_clause(project_id)
    rows = con.execute(
        """
        SELECT *,
          CASE
            WHEN key LIKE ? THEN 5
            WHEN title LIKE ? THEN 4
            WHEN decision LIKE ? THEN 3
            WHEN rationale LIKE ? THEN 2
            WHEN enforcement_hint LIKE ? THEN 1
            ELSE 0
          END AS relevance
        FROM brain_decisions
        WHERE """ + project_clause + """ AND scope = ? AND (
            key LIKE ? OR title LIKE ? OR decision LIKE ?
            OR rationale LIKE ? OR enforcement_hint LIKE ?
        )
        ORDER BY relevance DESC, status = 'active' DESC, confidence DESC, updated_at DESC, id DESC
        LIMIT ?
        """,
        (like, like, like, like, like, *project_params, scope, like, like, like, like, like, int(limit)),
    ).fetchall()
    return [decision_row_to_dict(row) for row in rows]


def disable_decision(con, project_id, key, scope="project"):
    now = iso_now()
    project_clause, project_params = _project_key_clause(project_id)
    cur = con.execute(
        f"""
        UPDATE brain_decisions
        SET status = 'disabled', updated_at = ?
        WHERE {project_clause} AND scope = ? AND key = ?
        """,
        (now, *project_params, scope, key),
    )
    con.commit()
    if cur.rowcount < 1:
        return None
    return get_decision(con, project_id, key, scope=scope)


def format_decision_context(decision):
    text = decision["decision"]
    forbidden = decision.get("forbidden_patterns") or []
    required = decision.get("required_patterns") or []
    if forbidden:
        text += " Avoid: " + ", ".join(forbidden[:4]) + "."
    if required:
        text += " Use: " + ", ".join(required[:4]) + "."
    redacted, _ = redact_text(text, max_length=1200)
    return redacted


def render_decisions(items):
    if not items:
        return "No implementation decisions found."
    lines = []
    for item in items:
        lines.append(f"[{item['key']}] {item['title']} ({item['status']}, confidence {item['confidence']}/10)")
        lines.append(f"  {item['decision']}")
    return "\n".join(lines)


def _project_root(project):
    root = project.get("root") if isinstance(project, dict) else None
    if root:
        return Path(root).resolve()
    display = project.get("root_path_display") if isinstance(project, dict) else None
    return Path(display or ".").resolve()


def _is_generated(path, root):
    try:
        rel = path.resolve().relative_to(root)
        return any(part in GENERATED_FOLDERS for part in rel.parts)
    except Exception:
        return True


def _relative_path(path, root):
    try:
        return path.resolve().relative_to(root).as_posix()
    except Exception:
        return path.as_posix()


def _has_glob(pattern):
    return any(ch in pattern for ch in "*?[")


def _matched_paths(root, pattern):
    pattern = str(pattern or "").strip()
    if not pattern:
        return [], False
    if Path(pattern).is_absolute():
        path = Path(pattern)
        return ([path] if path.exists() else []), False
    if _has_glob(pattern):
        matches = [path for path in root.glob(pattern) if path.is_file()]
        return matches, True
    path = root / pattern
    if path.is_file():
        return [path], False
    if path.is_dir():
        return [p for p in path.rglob("*") if p.is_file()], False
    return [], False


def _line_is_informational(line):
    lowered = line.lower()
    return any(marker in lowered for marker in ("fixture", "expected", "allowed example", "test fixture"))


def _is_informational_match(decision_key, rel, line):
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    if _line_is_informational(line) or fnmatch.fnmatch(rel, "tests/*") or fnmatch.fnmatch(rel, "docs/*.md"):
        return True
    if decision_key == "runtime-python-provider" and rel in ("scripts/os.sh", "scripts/runtime.sh"):
        return True
    if decision_key == "runtime-python-provider" and "command -v python" in line:
        return True
    if decision_key == "no-claude-in-hooks" and rel == "scripts/handover.sh":
        return True
    return False


def _matches_forbidden(line, pattern):
    command = str(pattern or "").strip()
    if command in ("python", "python3"):
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(command)}\s", line) is not None
    return bool(pattern and pattern in line)


def check_decisions(con, project, key=None, record_regressions=False):
    root = _project_root(project)
    project_id = project["id"]
    if key:
        decision = get_decision(con, project_id, key)
        decisions = [decision] if decision and decision["status"] == "active" else []
    else:
        decisions = list_decisions(con, project_id, status="active", limit=100)

    violations = []
    warnings = []
    missing_paths = []
    checked_files = set()
    skipped_files = []

    for decision in decisions:
        files = []
        for pattern in decision.get("applies_to") or []:
            matches, was_glob = _matched_paths(root, pattern)
            if not matches:
                missing_paths.append({"decision_key": decision["key"], "pattern": pattern, "glob": was_glob})
                continue
            files.extend(matches)

        unique_files = []
        seen = set()
        for path in files:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if _is_generated(path, root):
                skipped_files.append(_relative_path(path, root))
                continue
            unique_files.append(path)

        found_required = {pattern: False for pattern in decision.get("required_patterns") or []}
        for path in unique_files:
            rel = _relative_path(path, root)
            checked_files.add(rel)
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception as exc:
                warnings.append({"decision_key": decision["key"], "path": rel, "warning": f"could not read file: {exc}"})
                continue

            for line_no, line in enumerate(lines, 1):
                for pattern in decision.get("required_patterns") or []:
                    if pattern and pattern in line:
                        found_required[pattern] = True
                for pattern in decision.get("forbidden_patterns") or []:
                    if not _matches_forbidden(line, pattern):
                        continue
                    redacted_line, status = redact_text(line, max_length=500)
                    severity = "info" if _is_informational_match(decision["key"], rel, line) else "warn"
                    item = {
                        "decision_key": decision["key"],
                        "title": decision["title"],
                        "pattern": pattern,
                        "path": rel,
                        "line": line_no,
                        "line_redacted": redacted_line.strip(),
                        "redaction_status": status,
                        "severity": severity,
                    }
                    violations.append(item)

        for pattern, found in found_required.items():
            if unique_files and not found:
                warnings.append(
                    {
                        "decision_key": decision["key"],
                        "pattern": pattern,
                        "warning": "required pattern was not found in scanned files",
                    }
                )

    missing_exact_count = sum(1 for item in missing_paths if not item.get("glob"))
    warn_count = sum(1 for item in violations if item["severity"] == "warn") + len(warnings) + missing_exact_count
    result = {
        "status": "warn" if warn_count else "pass",
        "decisions_checked": len(decisions),
        "checked_files": sorted(checked_files),
        "skipped_generated_files": sorted(set(skipped_files)),
        "missing_paths": missing_paths,
        "violations": violations,
        "warnings": warnings,
        "violation_count": sum(1 for item in violations if item["severity"] == "warn"),
    }
    if record_regressions and result["violation_count"]:
        try:
            from .capture import upsert_candidate

            for item in violations:
                if item["severity"] != "warn":
                    continue
                upsert_candidate(
                    con,
                    project_id,
                    candidate_type="regression_warning",
                    key=f"decision-regression-{item['decision_key']}",
                    title=f"Forbidden pattern for {item['decision_key']} reappeared",
                    body=f"{item['path']}:{item['line']} matched forbidden pattern {item['pattern']}",
                    rationale="Active implementation decision check found a regression signal.",
                    proposed_target="none",
                    evidence={"violation": item},
                    confidence=7,
                    source="decisions-check",
                )
        except Exception:
            pass
    return result


def render_check_result(result):
    lines = [
        "LBrain decision check",
        f"Decisions checked: {result['decisions_checked']}",
        f"Files scanned: {len(result['checked_files'])}",
    ]
    if result["missing_paths"]:
        lines.append("Missing applies-to paths:")
        for item in result["missing_paths"]:
            lines.append(f"  [{item['decision_key']}] {item['pattern']}")
    warn_violations = [item for item in result["violations"] if item["severity"] == "warn"]
    info_violations = [item for item in result["violations"] if item["severity"] == "info"]
    if warn_violations:
        lines.append("Warnings:")
        for item in warn_violations:
            lines.append(
                f"  [{item['decision_key']}] {item['path']}:{item['line']} contains {item['pattern']}: {item['line_redacted']}"
            )
    if info_violations:
        lines.append("Informational matches:")
        for item in info_violations:
            lines.append(f"  [{item['decision_key']}] {item['path']}:{item['line']} contains informational text")
    if result["warnings"]:
        lines.append("Required pattern warnings:")
        for item in result["warnings"]:
            lines.append(f"  [{item['decision_key']}] {item.get('pattern') or item.get('path')}: {item['warning']}")
    if not result["missing_paths"] and not warn_violations and not result["warnings"]:
        lines.append("No decision violations found.")
    lines.append(f"Status: {result['status']}")
    return "\n".join(lines)


def seed_lstack_default_decisions(con, project):
    root = _project_root(project)
    if not is_lstack_project({**project, "root": root}):
        return []
    added = []

    bin_text = (root / "bin" / "lstack").read_text(encoding="utf-8", errors="ignore")
    scripts_os = root / "scripts" / "os.sh"
    os_text = scripts_os.read_text(encoding="utf-8", errors="ignore") if scripts_os.exists() else ""
    if not get_decision(con, project["id"], "runtime-python-provider") and "run_python" in bin_text and "py -3" in (bin_text + os_text):
        added.append(
            add_decision(
                con,
                project["id"],
                key="runtime-python-provider",
                title="Use lstack runtime for Python execution",
                decision="All lstack production scripts and hooks must use the runtime Python provider or run_python helper instead of direct python/python3 calls.",
                rationale="Windows Git Bash may only have py -3. Direct python/python3 calls caused cross-platform failures.",
                enforcement_hint="Scan bin/lstack, hooks/*.sh, and scripts/*.sh for direct python/python3 usage.",
                forbidden_patterns=["python3 ", "python "],
                required_patterns=["run_python"],
                applies_to=["bin/lstack", "hooks/*.sh", "scripts/*.sh"],
                evidence={
                    "references": ["bin/lstack", "scripts/os.sh"],
                    "summary": "run_python exists and py -3 support is present.",
                },
                source="detected",
                confidence=10,
            )
        )

    docs_text = ""
    for rel in ("README.md", "docs/lbrain.md"):
        path = root / rel
        if path.exists():
            docs_text += "\n" + path.read_text(encoding="utf-8", errors="ignore")
    if not get_decision(con, project["id"], "git-bash-not-wsl") and "Git Bash" in docs_text and "not WSL" in docs_text:
        added.append(
            add_decision(
                con,
                project["id"],
                key="git-bash-not-wsl",
                title="Use Git Bash paths on Windows, not WSL paths",
                decision="On Windows, lstack must target Git Bash and MSYS2-style /c/... or /d/... paths, not WSL /mnt/c/... paths.",
                forbidden_patterns=["/mnt/c/", "/mnt/d/"],
                required_patterns=["/c/"],
                applies_to=["bin/lstack", "hooks/*.sh", "scripts/*.sh", "docs/*.md"],
                evidence={"references": ["README.md", "docs/lbrain.md"], "summary": "Docs state Windows support targets Git Bash, not WSL."},
                source="detected",
                confidence=10,
            )
        )

    if not get_decision(con, project["id"], "no-claude-in-hooks") and "claude -p" in docs_text and "disabled by default" in docs_text:
        added.append(
            add_decision(
                con,
                project["id"],
                key="no-claude-in-hooks",
                title="Lifecycle hooks must not call Claude recursively",
                decision="Lifecycle hooks must not call claude -p by default.",
                rationale="Calling claude -p from Stop or PreCompact can recursively start new Claude sessions.",
                forbidden_patterns=["claude -p"],
                applies_to=["hooks/*.sh", "hooks/*.py", "scripts/*.sh", "scripts/*.py"],
                evidence={"references": ["README.md"], "summary": "Docs state automatic LLM extraction from transcripts is disabled by default."},
                source="detected",
                confidence=9,
            )
        )

    return added
