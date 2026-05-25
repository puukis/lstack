"""Tests for LBrain Change Receipts."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.capture import list_events, record_event
from brain.contracts import create_contract
from brain.db import connect, ensure_project
from brain.receipts import (
    GitReceiptError,
    abandon_receipt,
    attach_capture_event,
    finalize_receipt,
    get_open_receipt,
    get_receipt,
    list_receipts,
    record_command,
    record_test,
    render_receipt_explain,
    require_git_worktree,
    start_receipt,
)
from brain.schema import init_schema, missing_phase_1d_tables

BRAIN_CLI = ROOT / "lbrain" / "brain.py"


def _git_env():
    env = os.environ.copy()
    if os.name == "nt":
        env.setdefault("MSYSTEM", "MINGW64")
    return env


def _patch_git_bash_env():
    if os.name == "nt":
        return patch.dict(os.environ, {"MSYSTEM": "MINGW64"}, clear=False)
    return patch.dict(os.environ, {}, clear=False)


def _run_git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_git_env(),
        timeout=20,
        check=True,
    )


def _make_repo(tmp):
    repo = Path(tmp)
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "initial")
    return repo


def _run_brain(repo, db_path, *args):
    env = _git_env()
    env["LSTACK_DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, str(BRAIN_CLI), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@unittest.skipUnless(shutil.which("git"), "git not available")
class TestReceiptSchema(unittest.TestCase):
    def test_receipt_tables_created_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = connect(Path(tmp) / "lstack.db")
            init_schema(con)
            self.assertEqual(missing_phase_1d_tables(con), [])
            init_schema(con)
            self.assertEqual(missing_phase_1d_tables(con), [])
            con.close()


@unittest.skipUnless(shutil.which("git"), "git not available")
class TestReceiptLifecycle(unittest.TestCase):
    def test_start_creates_open_receipt_inside_git_worktree(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            receipt = start_receipt(con, project, title="Receipt smoke", goal="Test lifecycle")
            con.close()
        self.assertEqual(receipt["status"], "open")
        self.assertEqual(receipt["title"], "Receipt smoke")
        self.assertTrue(receipt["base_commit"])
        self.assertTrue(receipt["git_root"])

    def test_start_fails_outside_git_worktree(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            con = connect(Path(tmp) / "lstack.db")
            project = ensure_project(con, tmp)
            with self.assertRaises(GitReceiptError) as ctx:
                start_receipt(con, project, title="Should fail")
            con.close()
        self.assertIn("Change Receipts require a git worktree", str(ctx.exception))

    def test_start_fails_when_git_executable_missing(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            with patch("brain.receipts.shutil.which", return_value=None):
                with self.assertRaises(GitReceiptError) as ctx:
                    start_receipt(con, project, title="No git")
            con.close()
        self.assertIn("git on PATH", str(ctx.exception))

    def test_at_most_one_open_receipt_unless_override(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            first = start_receipt(con, project, title="First")
            with self.assertRaises(ValueError):
                start_receipt(con, project, title="Second")
            second = start_receipt(con, project, title="Second", allow_multiple=True)
            con.close()
        self.assertNotEqual(first["id"], second["id"])

    def test_replace_abandons_previous_open_receipt(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            first = start_receipt(con, project, title="First")
            second = start_receipt(con, project, title="Second", replace=True)
            old = get_receipt(con, project["id"], first["id"])
            con.close()
        self.assertEqual(old["status"], "abandoned")
        self.assertEqual(second["status"], "open")

    def test_finalize_marks_finalized_and_captures_diff_stats(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            receipt = start_receipt(con, project, title="Finalize")
            (repo / "README.md").write_text("initial\nchanged\n", encoding="utf-8")
            record_test(con, project["id"], "py -3 -m unittest tests.test_brain_receipts -v", result="pass")
            finalized = finalize_receipt(con, project, receipt_id=receipt["id"], summary="Done")
            con.close()
        self.assertEqual(finalized["status"], "finalized")
        self.assertEqual(finalized["summary"], "Done")
        self.assertTrue(finalized["head_commit"])
        self.assertTrue(finalized["working_tree_dirty_end"])
        self.assertGreaterEqual(len(finalized["files_changed"]), 1)
        self.assertGreaterEqual(len(finalized["diff_stat"]), 1)

    def test_abandon_marks_abandoned(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            receipt = start_receipt(con, project, title="Abandon")
            abandoned = abandon_receipt(con, project["id"], receipt["id"], reason="Not needed")
            con.close()
        self.assertEqual(abandoned["status"], "abandoned")
        self.assertIn("Not needed", abandoned["summary"])

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            receipt = start_receipt(con, project, title="JSON")
            data = json.loads(json.dumps({"receipt": receipt}))
            con.close()
        self.assertEqual(data["receipt"]["title"], "JSON")

    def test_record_command_and_test_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Commands")
            receipt = record_command(con, project["id"], "echo hello", result="pass")
            receipt = record_test(con, project["id"], "rm -rf should-not-run", result="unknown")
            con.close()
        self.assertEqual(receipt["commands"][0]["result"], "pass")
        self.assertEqual(receipt["tests"][0]["result"], "unknown")
        self.assertFalse((repo / "should-not-run").exists())

    def test_attach_event_links_capture_event(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Attach")
            event_result = record_event(
                con,
                project["id"],
                "failed_command",
                "Command failed",
                command="python3 missing.py",
                evidence={"exit_code": 127},
                allow_auto_promote=False,
            )
            receipt = attach_capture_event(con, project["id"], event_result["event"]["id"])
            con.close()
        self.assertIn(event_result["event"]["id"], receipt["capture_event_ids"])
        self.assertEqual(receipt["commands"][0]["result"], "fail")

    def test_auto_learned_candidate_ids_can_be_shown(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Auto learned")
            last_event_id = None
            for _ in range(2):
                result = record_event(
                    con,
                    project["id"],
                    "failed_command",
                    "Command failed",
                    command="python3 missing.py",
                    evidence={"exit_code": 127},
                    allow_auto_promote=False,
                )
                last_event_id = result["event"]["id"]
            receipt = attach_capture_event(con, project["id"], last_event_id)
            con.close()
        self.assertTrue(receipt["auto_learned_ids"])

    def test_contract_link_and_violation_explain(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            create_contract(
                con,
                project["id"],
                task_goal="Only docs",
                allowed_files=["docs/**"],
                forbidden_files=["install.sh"],
            )
            receipt = start_receipt(con, project, title="Contract")
            (repo / "install.sh").write_text("bad\n", encoding="utf-8")
            finalized = finalize_receipt(con, project, receipt["id"], summary="Done")
            explanation = render_receipt_explain(
                {
                    "receipt": finalized,
                    "why": finalized["goal"],
                    "captured": {"files_changed": len(finalized["files_changed"]), "commands": 0, "tests": 0, "capture_events": 0, "auto_learned": 0},
                    "missing": ["tests"],
                    "contract_status": finalized["contract_check"].get("status"),
                    "review": finalized["review_notes"],
                }
            )
            con.close()
        self.assertEqual(receipt["contract_id"], finalized["contract_id"])
        self.assertIn(finalized["contract_check"].get("status"), ("warn", "violation"))
        self.assertIn("Contract", explanation)

    def test_no_active_contract_is_okay(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            receipt = start_receipt(con, project, title="No contract")
            finalized = finalize_receipt(con, project, receipt["id"])
            con.close()
        self.assertIsNone(finalized["contract_id"])
        self.assertEqual(finalized["contract_check"], {})

    def test_undo_hint_prints_but_does_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            receipt = start_receipt(con, project, title="Undo")
            hint = receipt["undo_hint"]
            con.close()
        self.assertIn("git diff", hint)
        self.assertIn("never executes", hint)

    def test_receipt_git_runner_rejects_mutating_commands(self):
        from brain import receipts
        with self.assertRaises(GitReceiptError):
            receipts._run_git_readonly(["reset", "--hard"])

    def test_git_root_path_normalization_no_wsl_for_git_bash(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            info = require_git_worktree(repo)
        self.assertNotIn("/mnt/c/", info["git_root"])

    def test_wsl_shell_mode_is_not_git_bash(self):
        from brain.platform import platform_facts
        with patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=False):
            os.environ.pop("MSYSTEM", None)
            facts = platform_facts(system_name="Linux", proc_version="microsoft")
        self.assertEqual(facts["shell_mode"], "wsl")


@unittest.skipUnless(shutil.which("git"), "git not available")
class TestReceiptCli(unittest.TestCase):
    def test_cli_start_status_list_show_finalize_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            db_path = repo / "lstack.db"
            r = _run_brain(repo, db_path, "receipt", "start", "--title", "CLI", "--goal", "Exercise CLI", "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            receipt = json.loads(r.stdout)["receipt"]

            status = _run_brain(repo, db_path, "receipt", "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)["open_receipt"]["id"], receipt["id"])

            listing = _run_brain(repo, db_path, "receipt", "list", "--json")
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual(len(json.loads(listing.stdout)["receipts"]), 1)

            shown = _run_brain(repo, db_path, "receipt", "show", str(receipt["id"]), "--json")
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(json.loads(shown.stdout)["receipt"]["title"], "CLI")

            _run_brain(repo, db_path, "receipt", "record-command", "--command", "echo hello", "--result", "pass")
            _run_brain(repo, db_path, "receipt", "record-test", "--command", "py -3 -m unittest tests.test_brain_receipts -v", "--result", "pass")
            final = _run_brain(repo, db_path, "receipt", "finalize", "--summary", "CLI done", "--json")
            self.assertEqual(final.returncode, 0, final.stderr)
            self.assertEqual(json.loads(final.stdout)["receipt"]["status"], "finalized")

    def test_cli_start_fails_clearly_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            r = _run_brain(tmp, db_path, "receipt", "start", "--title", "No git")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Change Receipts require a git worktree", r.stderr)


if __name__ == "__main__":
    unittest.main()
