"""Repo-wide guard: runtime user-facing output must not contain roadmap phase labels."""

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.db import connect
from brain.doctor import render_doctor, run_doctor

# Forbidden in any user-facing output
FORBIDDEN = re.compile(
    r"Phase\s+1[ABCD]|phase\s+1[abcd]|phase1[abcd]|schema\.phase1[abcd]",
    re.IGNORECASE,
)

# Paths that may legitimately contain phase labels (internal roadmap / test allowlist)
_ALLOWLISTED_PATHS = {
    "paste-cache",
    "file-history",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    # This file itself asserts the ban — the pattern strings here are not runtime output
    "test_user_facing_feature_names.py",
}

# File extensions to audit for user-facing string content
_AUDIT_EXTENSIONS = {".py", ".sh", ".md", ".txt", ".json"}

# These source files/dirs are explicitly internal-roadmap and may use phase labels
_ROADMAP_FILES = {
    "docs/roadmap.md",
    "docs/internal-roadmap.md",
    "CHANGELOG.md",
}


def _is_allowlisted(path: Path) -> bool:
    parts = set(path.parts)
    if parts & _ALLOWLISTED_PATHS:
        return True
    rel = path.relative_to(ROOT) if ROOT in path.parents or path == ROOT else None
    if rel and str(rel).replace("\\", "/") in _ROADMAP_FILES:
        return True
    return False


class TestDoctorOutputHasNoPhaseLabels(unittest.TestCase):
    """Doctor output must use product feature names, not roadmap phase labels."""

    def _run_doctor_rendered(self, db_path):
        result = run_doctor(db_path)
        return render_doctor(result), result

    def test_doctor_full_db_output_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = connect(db_path)
            con.close()
            rendered, result = self._run_doctor_rendered(db_path)
            match = FORBIDDEN.search(rendered)
            if match:
                self.fail(f"Phase label in doctor output: {match.group()!r}\nFull output:\n{rendered}")

    def test_doctor_empty_db_output_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            import sqlite3
            db_path = Path(tmp) / "lstack.db"
            con = sqlite3.connect(str(db_path))
            con.execute("CREATE TABLE brain_projects (id INTEGER PRIMARY KEY)")
            con.close()
            rendered, _ = self._run_doctor_rendered(db_path)
            match = FORBIDDEN.search(rendered)
            if match:
                self.fail(f"Phase label in doctor output (empty db): {match.group()!r}\nFull:\n{rendered}")

    def test_doctor_check_ids_have_no_phase_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = connect(db_path)
            con.close()
            _, result = self._run_doctor_rendered(db_path)
            for check in result["checks"]:
                m = FORBIDDEN.search(check["id"])
                if m:
                    self.fail(f"Phase label in check id {check['id']!r}: {m.group()!r}")
                m = FORBIDDEN.search(check["message"])
                if m:
                    self.fail(f"Phase label in check message for {check['id']!r}: {m.group()!r} in {check['message']!r}")

    def test_doctor_uses_feature_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = connect(db_path)
            con.close()
            rendered, result = self._run_doctor_rendered(db_path)
            checks = {c["id"]: c for c in result["checks"]}
            self.assertIn("schema.capture", checks, "Expected schema.capture check in doctor")
            self.assertIn("schema.task_contracts", checks, "Expected schema.task_contracts check in doctor")
            self.assertIn("receipts.schema", checks, "Expected receipts.schema check in doctor")
            self.assertIn("Change Receipts", checks["receipts.schema"]["message"])
            self.assertIn("Task Contracts", checks["schema.task_contracts"]["message"])
            self.assertIn("Capture", checks["schema.capture"]["message"])

    def test_contracts_active_warn_uses_feature_name(self):
        """When Task Contracts tables are missing, doctor must say 'Task Contracts', not 'Phase 1C'."""
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = sqlite3.connect(str(db_path))
            # Only create Phase 1A tables so 1C tables are missing
            con.executescript("""
                CREATE TABLE brain_projects (id INTEGER PRIMARY KEY,
                    root_path_hash TEXT NOT NULL, root_path_display TEXT,
                    repo_id TEXT, git_remote_hash TEXT, git_branch TEXT,
                    name TEXT, platform TEXT, shell_mode TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(root_path_hash));
                CREATE TABLE brain_passports (id INTEGER PRIMARY KEY, project_id INTEGER);
                CREATE TABLE brain_attempts (id INTEGER PRIMARY KEY, project_id INTEGER);
                CREATE TABLE brain_context_decisions (id INTEGER PRIMARY KEY, project_id INTEGER);
                CREATE TABLE brain_decisions (id INTEGER PRIMARY KEY, project_id INTEGER);
                CREATE TABLE brain_capture_events (id INTEGER PRIMARY KEY, project_id INTEGER);
                CREATE TABLE brain_memory_candidates (id INTEGER PRIMARY KEY, project_id INTEGER);
            """)
            con.close()
            rendered, result = self._run_doctor_rendered(db_path)
            checks = {c["id"]: c for c in result["checks"]}
            contracts_msg = checks.get("contracts.active", {}).get("message", "")
            m = FORBIDDEN.search(contracts_msg)
            if m:
                self.fail(f"Phase label in contracts.active message: {m.group()!r} in {contracts_msg!r}")
            receipts_msg = checks.get("receipts.open", {}).get("message", "")
            m = FORBIDDEN.search(receipts_msg)
            if m:
                self.fail(f"Phase label in receipts.open message: {m.group()!r} in {receipts_msg!r}")


class TestRepoSourceAudit(unittest.TestCase):
    """Source files that produce runtime output must not contain phase labels in string literals."""

    # Exact file paths (relative to ROOT) where phase labels are allowed to appear
    ALLOWLISTED_FILES = frozenset({
        "docs/roadmap.md",
        "docs/internal-roadmap.md",
        "CHANGELOG.md",
        # This test file itself
        "tests/test_user_facing_feature_names.py",
    })

    # Directory names that are never user-facing source
    ALLOWLISTED_DIRS = frozenset({
        "paste-cache",
        "file-history",
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "projects",
        "logs",
    })

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(ROOT)).replace("\\", "/")

    def _should_skip(self, path: Path) -> bool:
        rel = self._rel(path)
        if rel in self.ALLOWLISTED_FILES:
            return True
        for part in path.parts:
            if part in self.ALLOWLISTED_DIRS:
                return True
        return False

    def _audit_files(self, *dirs, extensions=None):
        exts = extensions or {".py", ".sh", ".md"}
        violations = []
        for d in dirs:
            target = ROOT / d if not Path(d).is_absolute() else Path(d)
            if not target.exists():
                continue
            for f in target.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix not in exts:
                    continue
                if self._should_skip(f):
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for m in FORBIDDEN.finditer(text):
                    line_no = text[: m.start()].count("\n") + 1
                    violations.append(f"{self._rel(f)}:{line_no}: {m.group()!r}")
        return violations

    def test_lbrain_source_has_no_phase_labels(self):
        violations = self._audit_files("lbrain")
        self.assertEqual(violations, [],
            "Phase labels found in lbrain/ source:\n" + "\n".join(violations))

    def test_hooks_source_has_no_phase_labels(self):
        violations = self._audit_files("hooks")
        self.assertEqual(violations, [],
            "Phase labels found in hooks/:\n" + "\n".join(violations))

    def test_bin_source_has_no_phase_labels(self):
        violations = self._audit_files("bin")
        self.assertEqual(violations, [],
            "Phase labels found in bin/:\n" + "\n".join(violations))

    def test_scripts_source_has_no_phase_labels(self):
        violations = self._audit_files("scripts")
        self.assertEqual(violations, [],
            "Phase labels found in scripts/:\n" + "\n".join(violations))

    def test_tests_source_has_no_phase_labels_in_assertions(self):
        """Test files must not assert old phase-label check IDs like schema.phase1b."""
        old_check_ids = re.compile(
            r"schema\.phase1[abcd]", re.IGNORECASE
        )
        violations = []
        tests_dir = ROOT / "tests"
        for f in tests_dir.glob("*.py"):
            if f.name == "test_user_facing_feature_names.py":
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in old_check_ids.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                violations.append(f"tests/{f.name}:{line_no}: {m.group()!r}")
        self.assertEqual(violations, [],
            "Old phase-label check IDs found in test assertions:\n" + "\n".join(violations))

    def test_docs_user_facing_has_no_phase_labels(self):
        """User-facing docs must use feature names, not phase labels."""
        violations = self._audit_files("docs")
        self.assertEqual(violations, [],
            "Phase labels found in docs/:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
