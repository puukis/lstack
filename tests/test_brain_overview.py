"""Tests for lstack brain overview --json."""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.attempts import add_attempt
from brain.db import connect, ensure_project
from brain.decisions import add_decision

FORBIDDEN_PHASE = re.compile(
    r"Phase\s+1[ABCD]|phase\s+1[abcd]|phase1[abcd]",
    re.IGNORECASE,
)
FORBIDDEN_SECRETS = re.compile(
    r"ghp_[A-Za-z0-9]{10,}|GITHUB_TOKEN\s*=\s*\S+|sk-[A-Za-z0-9]{10,}",
)


def _make_project(tmp):
    root = Path(tmp)
    con = connect(root / "lstack.db")
    project = ensure_project(con, root)
    return con, project, root


def _get_overview(tmp, con=None, project=None):
    if con is None:
        con, project, _ = _make_project(tmp)
    from brain.overview import build_overview
    return build_overview(con, project), con


class TestOverviewSchema(unittest.TestCase):
    """Tests 32-43: overview JSON schema."""

    def test_overview_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertEqual(data["schema_version"], 1)

    def test_overview_includes_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("project", data)
            self.assertIn("name", data["project"])
            self.assertIn("git_branch", data["project"])
            self.assertIn("id", data["project"])

    def test_overview_includes_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("platform", data)
            self.assertIn("os", data["platform"])
            self.assertIn("shell_mode", data["platform"])
            self.assertIn("path_rule", data["platform"])

    def test_overview_includes_passport(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("passport", data)
            self.assertIn("available", data["passport"])

    def test_overview_includes_context_governor(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("context_governor", data)
            gov = data["context_governor"]
            self.assertIn("target", gov)
            self.assertIn("included_count", gov)
            self.assertIn("skipped_count", gov)
            self.assertIn("estimated_tokens", gov)
            self.assertGreater(gov["included_count"], 0)

    def test_overview_includes_firewall(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("firewall", data)
            fw = data["firewall"]
            self.assertIn("available", fw)
            self.assertIn("status", fw)
            self.assertIn("warning_count", fw)
            self.assertIn("top_warnings", fw)
            self.assertTrue(fw["available"])

    def test_overview_includes_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("contracts", data)
            self.assertIn("active", data["contracts"])
            self.assertIn("active_count", data["contracts"])

    def test_overview_includes_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("receipts", data)
            self.assertIn("open", data["receipts"])
            self.assertIn("recent", data["receipts"])
            self.assertIsInstance(data["receipts"]["recent"], list)

    def test_overview_includes_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("decisions", data)
            self.assertIn("active_count", data["decisions"])
            self.assertIn("top", data["decisions"])

    def test_overview_includes_failed_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("failed_attempts", data)
            self.assertIn("count", data["failed_attempts"])
            self.assertIn("top", data["failed_attempts"])

    def test_overview_includes_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("capture", data)
            cap = data["capture"]
            self.assertIn("events_count", cap)
            self.assertIn("pending_candidates_count", cap)
            self.assertIn("promoted_candidates_count", cap)
            self.assertIn("recent_events", cap)
            self.assertIn("pending_candidates", cap)

    def test_overview_includes_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertIn("doctor", data)
            self.assertIn("status", data["doctor"])
            self.assertIn("warnings", data["doctor"])
            self.assertIn("failures", data["doctor"])

    def test_overview_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            serialized = json.dumps(data, indent=2)
            parsed = json.loads(serialized)
            self.assertEqual(parsed["schema_version"], 1)


class TestOverviewSafety(unittest.TestCase):
    """Tests 45-48: overview output safety."""

    def test_overview_no_full_diffs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            text = json.dumps(data)
            self.assertNotIn("old_str", text)
            self.assertNotIn("new_str", text)

    def test_overview_no_full_command_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            # Add an attempt with potential verbose output
            add_attempt(
                con, project["id"],
                "npm install",
                command="npm install",
                why_failed="Uses pnpm",
                confidence=8,
                retry_policy="never",
            )
            data, _ = _get_overview(tmp, con=con, project=project)
            con.close()
            # Attempts in overview should be truncated summaries
            for attempt in data["failed_attempts"]["top"]:
                self.assertLessEqual(
                    len(attempt.get("attempted_action", "")), 100,
                    "Overview should not include full command output",
                )

    def test_overview_no_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            add_decision(
                con, project["id"],
                key="secret-overview-dec",
                title="Secret",
                decision="Do not use GITHUB_TOKEN=ghp_fakefakefake.",
                confidence=8,
            )
            data, _ = _get_overview(tmp, con=con, project=project)
            con.close()
            text = json.dumps(data)
            self.assertIsNone(FORBIDDEN_SECRETS.search(text), "Secret found in overview output")

    def test_overview_no_phase_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            text = json.dumps(data)
            self.assertIsNone(FORBIDDEN_PHASE.search(text), "Phase label found in overview output")


class TestOverviewEmptyDB(unittest.TestCase):
    """Tests 49-51: overview works with minimal/empty state."""

    def test_overview_works_with_empty_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, con = _get_overview(tmp)
            con.close()
            self.assertEqual(data["schema_version"], 1)
            self.assertIn("project", data)
            self.assertEqual(data["failed_attempts"]["count"], 0)
            self.assertEqual(data["decisions"]["active_count"], 0)

    def test_overview_counts_correct_after_adds(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            add_attempt(
                con, project["id"],
                "npm install",
                why_failed="Uses pnpm",
                retry_policy="never",
                confidence=9,
            )
            add_decision(
                con, project["id"],
                key="test-ov-dec",
                title="Test",
                decision="Use correct approach.",
                confidence=9,
            )
            data, _ = _get_overview(tmp, con=con, project=project)
            con.close()
            self.assertGreaterEqual(data["failed_attempts"]["count"], 1)
            self.assertGreaterEqual(data["decisions"]["active_count"], 1)

    def test_overview_does_not_mutate_db_unexpectedly(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            before_receipts = con.execute(
                "SELECT COUNT(*) FROM brain_change_receipts WHERE project_id = ?",
                (project["id"],),
            ).fetchone()[0]
            _get_overview(tmp, con=con, project=project)
            after_receipts = con.execute(
                "SELECT COUNT(*) FROM brain_change_receipts WHERE project_id = ?",
                (project["id"],),
            ).fetchone()[0]
            con.close()
            self.assertEqual(before_receipts, after_receipts)


class TestOverviewHumanOutput(unittest.TestCase):
    """Test 44: human-readable output is compact."""

    def test_overview_cli_human_output(self):
        import subprocess, sys, os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            db_path = root / "test.db"
            env = {**os.environ, "LSTACK_DB_PATH": str(db_path)}
            result = subprocess.run(
                [sys.executable, str(ROOT / "lbrain" / "brain.py"), "overview"],
                capture_output=True, text=True, env=env, cwd=str(root),
            )
            out = result.stdout
            self.assertIn("LBrain overview", out)
            self.assertIn("Platform:", out)
            self.assertIsNone(FORBIDDEN_PHASE.search(out), "Phase label in human output")

    def test_overview_cli_json_output(self):
        import subprocess, sys, os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            db_path = root / "test.db"
            env = {**os.environ, "LSTACK_DB_PATH": str(db_path)}
            result = subprocess.run(
                [sys.executable, str(ROOT / "lbrain" / "brain.py"), "overview", "--json"],
                capture_output=True, text=True, env=env, cwd=str(root),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["schema_version"], 1)
            self.assertIn("context_governor", data)
            self.assertIn("firewall", data)


if __name__ == "__main__":
    unittest.main()
