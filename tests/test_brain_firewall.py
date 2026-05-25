"""Tests for AI Mistake Firewall."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.attempts import add_attempt
from brain.db import connect, ensure_project
from brain.decisions import add_decision
from brain.firewall import (
    RULE_COUNT,
    firewall_explain,
    firewall_status,
    render_firewall_check,
    run_firewall_check,
)


def _make_project(tmp):
    root = Path(tmp)
    con = connect(root / "lstack.db")
    project = ensure_project(con, root)
    return con, project, root


def _facts_git_bash():
    return {"os": "windows", "shell_mode": "git-bash", "path_style": "Use /c/... paths."}


def _facts_linux():
    return {"os": "linux", "shell_mode": "bash", "path_style": "Use native POSIX paths."}


class TestFirewallPlatformChecks(unittest.TestCase):
    """Tests 14-15: platform-related checks."""

    def test_detects_mnt_path_on_git_bash(self):
        result = run_firewall_check(
            command="cat /mnt/c/Users/Leo/file.txt",
            facts=_facts_git_bash(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("git-bash-not-wsl", keys)
        self.assertEqual(result["status"], "warn")

    def test_no_mnt_warning_on_linux(self):
        result = run_firewall_check(
            command="cat /mnt/shared/file.txt",
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertNotIn("git-bash-not-wsl", keys)


class TestFirewallPythonChecks(unittest.TestCase):
    """Test 16: direct python in hook/script context."""

    def test_detects_python_in_hook_context(self):
        result = run_firewall_check(
            command="python3 scripts/db.py stats",
            paths=["scripts/run.py"],
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("runtime-python-provider", keys)

    def test_no_python_warning_outside_hook_script(self):
        result = run_firewall_check(
            command="python3 myapp.py",
            paths=[],
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertNotIn("runtime-python-provider", keys)


class TestFirewallClaudeP(unittest.TestCase):
    """Test 17: claude -p in hook/lifecycle context."""

    def test_detects_claude_p_in_hook(self):
        result = run_firewall_check(
            command="claude -p 'do something'",
            paths=["hooks/stop.sh"],
            facts=_facts_git_bash(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("no-claude-in-hooks", keys)
        high = [w for w in result["warnings"] if w["key"] == "no-claude-in-hooks"]
        self.assertEqual(high[0]["severity"], "high")
        self.assertTrue(high[0]["strict_exit_block"])

    def test_detects_claude_p_without_hook_context(self):
        result = run_firewall_check(
            command="claude -p 'do something'",
            paths=[],
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("no-claude-in-hooks", keys)


class TestFirewallCoAuthoredBy(unittest.TestCase):
    """Test 18: Co-Authored-By in commit."""

    def test_detects_co_authored_by_in_commit(self):
        cmd = "git commit -m 'test Co-Authored-By: Claude <noreply@anthropic.com>'"
        result = run_firewall_check(command=cmd, facts=_facts_linux())
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("no-coauthored-by-commits", keys)

    def test_no_warning_for_normal_commit(self):
        result = run_firewall_check(
            command="git commit -m 'feat: add new feature'",
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertNotIn("no-coauthored-by-commits", keys)


class TestFirewallProtectedFiles(unittest.TestCase):
    """Test 19: protected settings.json edit."""

    def test_detects_settings_json_edit(self):
        result = run_firewall_check(
            changed_files=["settings.json"],
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("protected-file-edit", keys)

    def test_detects_env_file_edit(self):
        result = run_firewall_check(
            changed_files=[".env"],
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("protected-file-edit", keys)


class TestFirewallGeneratedFolders(unittest.TestCase):
    """Test 20: generated folder edit."""

    def test_detects_pytest_cache_edit(self):
        result = run_firewall_check(
            changed_files=[".pytest_cache/v/cache/lastfailed"],
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("generated-folder-edit", keys)

    def test_detects_node_modules_edit(self):
        result = run_firewall_check(
            changed_files=["node_modules/some-pkg/index.js"],
            facts=_facts_linux(),
        )
        keys = [w["key"] for w in result["warnings"]]
        self.assertIn("generated-folder-edit", keys)


class TestFirewallContractChecks(unittest.TestCase):
    """Tests 21-22: contract pattern checks."""

    def test_detects_deny_pattern_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, root = _make_project(tmp)
            from brain.contracts import create_contract
            create_contract(
                con, project["id"],
                task_goal="Test task",
                allowed_files=["lbrain/**"],
                forbidden_files=["settings.json"],
            )
            result = run_firewall_check(
                changed_files=["settings.json"],
                con=con,
                project=project,
                facts=_facts_linux(),
            )
            con.close()
            keys = [w["key"] for w in result["warnings"]]
            self.assertIn("contract-deny-pattern", keys)
            high_w = [w for w in result["warnings"] if w["key"] == "contract-deny-pattern"]
            self.assertTrue(high_w[0]["strict_exit_block"])

    def test_detects_file_outside_allow_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, root = _make_project(tmp)
            from brain.contracts import create_contract
            create_contract(
                con, project["id"],
                task_goal="Narrow scope task",
                allowed_files=["lbrain/**"],
                forbidden_files=[],
            )
            result = run_firewall_check(
                changed_files=["tests/test_something.py"],
                con=con,
                project=project,
                facts=_facts_linux(),
            )
            con.close()
            keys = [w["key"] for w in result["warnings"]]
            self.assertIn("contract-allow-pattern", keys)


class TestFirewallReceiptChecks(unittest.TestCase):
    """Tests 23-24: receipt checks."""

    def test_detects_receipt_with_no_tests(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            con, project, root = _make_project(tmp)
            try:
                from brain.db import iso_now
                now = iso_now()
                con.execute(
                    """
                    INSERT INTO brain_change_receipts
                    (project_id, status, title, git_root, started_at, base_commit,
                     working_tree_dirty_start,
                     files_changed_json, diff_stat_json, tests_json, commands_json,
                     contract_check_json, decision_check_json,
                     capture_event_ids_json, auto_learned_ids_json,
                     redaction_status, privacy_class, source, created_at, updated_at)
                    VALUES (?, 'open', 'Test receipt', ?, ?, 'abc123',
                            1,
                            '["lbrain/brain.py"]', '{}', '[]', '[]',
                            '{}', '{}',
                            '[]', '[]',
                            'clean', 'local-only', 'manual', ?, ?)
                    """,
                    (project["id"], str(root), now, now, now),
                )
                con.commit()
                result = run_firewall_check(
                    changed_files=["lbrain/brain.py"],
                    con=con,
                    project=project,
                    facts=_facts_linux(),
                )
                keys = [w["key"] for w in result["warnings"]]
                self.assertIn("receipt-no-tests", keys)
            finally:
                con.close()

    def test_info_when_no_receipt_and_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, root = _make_project(tmp)
            result = run_firewall_check(
                changed_files=["lbrain/brain.py", "tests/test_brain.py", "docs/readme.md"],
                con=con,
                project=project,
                facts=_facts_linux(),
            )
            con.close()
            keys = [w["key"] for w in result["warnings"]]
            self.assertIn("no-open-receipt", keys)


class TestFirewallExitCodes(unittest.TestCase):
    """Tests 25-27: exit behavior."""

    def test_default_exit_0_on_warnings(self):
        # run_firewall_check returns result; caller decides exit code
        result = run_firewall_check(
            command="cat /mnt/c/Users/Leo/file.txt",
            facts=_facts_git_bash(),
        )
        self.assertEqual(result["status"], "warn")
        # Warnings present but no high+strict_exit_block
        high_strict = [w for w in result["warnings"] if w["severity"] == "high" and w["strict_exit_block"]]
        self.assertEqual(high_strict, [])

    def test_high_severity_on_claude_p_in_hook(self):
        result = run_firewall_check(
            command="claude -p test",
            paths=["hooks/stop.sh"],
            facts=_facts_git_bash(),
        )
        high_strict = [w for w in result["warnings"] if w["severity"] == "high" and w["strict_exit_block"]]
        self.assertTrue(len(high_strict) > 0)
        self.assertEqual(result["status"], "high")

    def test_json_output_is_valid(self):
        result = run_firewall_check(
            command="cat /mnt/c/test.txt",
            facts=_facts_git_bash(),
        )
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        self.assertIn("status", parsed)
        self.assertIn("warnings", parsed)
        self.assertIn("warning_count", parsed)


class TestFirewallNoExecution(unittest.TestCase):
    """Tests 29-31: firewall never executes, mutates, or calls Claude."""

    def test_firewall_does_not_execute_command(self):
        import os
        marker = Path(tempfile.gettempdir()) / "firewall_exec_test.txt"
        marker.unlink(missing_ok=True)
        run_firewall_check(
            command=f"touch {marker}",
            facts=_facts_linux(),
        )
        self.assertFalse(marker.exists(), "Firewall must never execute the checked command")

    def test_firewall_pass_result_has_no_warnings(self):
        result = run_firewall_check(
            command="pytest tests/",
            paths=[],
            changed_files=[],
            facts=_facts_linux(),
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["warnings"], [])


class TestFirewallNoPhaseNames(unittest.TestCase):
    """Test 28: no roadmap phase names in output."""

    def test_firewall_output_has_no_phase_labels(self):
        import re
        result = run_firewall_check(
            command="cat /mnt/c/Users/Leo/test.txt",
            facts=_facts_git_bash(),
        )
        text = json.dumps(result)
        forbidden = re.compile(r"Phase\s+1[ABCD]|phase\s+1[abcd]", re.IGNORECASE)
        self.assertIsNone(forbidden.search(text))

    def test_firewall_explain_no_phase_labels(self):
        import re
        data = firewall_explain()
        text = json.dumps(data)
        forbidden = re.compile(r"Phase\s+1[ABCD]|phase\s+1[abcd]", re.IGNORECASE)
        self.assertIsNone(forbidden.search(text))


class TestFirewallStatus(unittest.TestCase):
    """Firewall status command."""

    def test_firewall_status_has_rule_count(self):
        data = firewall_status()
        self.assertTrue(data["available"])
        self.assertEqual(data["rule_count"], RULE_COUNT)
        self.assertGreater(data["protected_patterns_count"], 0)

    def test_firewall_status_with_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            add_attempt(
                con, project["id"],
                "direct python3 scripts/db.py",
                why_failed="Should use run_python",
                retry_policy="never",
                confidence=9,
            )
            data = firewall_status(con, project)
            con.close()
            self.assertEqual(data["failed_attempts_count"], 1)


if __name__ == "__main__":
    unittest.main()
