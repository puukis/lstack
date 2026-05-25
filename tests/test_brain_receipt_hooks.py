"""Hook attachment tests for LBrain Change Receipts."""

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

from brain.autolearn import process_hook_payload
from brain.capture import list_events
from brain.contracts import create_contract
from brain.db import connect, ensure_project
from brain.receipts import get_open_receipt, list_receipt_events, start_receipt


def _git_env():
    env = os.environ.copy()
    if os.name == "nt":
        env.setdefault("MSYSTEM", "MINGW64")
    return env


def _patch_git_bash_env(extra=None):
    env = dict(extra or {})
    if os.name == "nt":
        env.setdefault("MSYSTEM", "MINGW64")
    return patch.dict(os.environ, env, clear=False)


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


def _bash_payload(command, exit_code=0, output=""):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"exit_code": exit_code, "output": output},
    }


def _file_payload(tool_name, file_path, extra=None):
    tool_input = {"file_path": str(file_path)}
    if extra:
        tool_input.update(extra)
    return {"tool_name": tool_name, "tool_input": tool_input, "tool_response": {}}


@unittest.skipUnless(shutil.which("git"), "git not available")
class TestReceiptHookAttachment(unittest.TestCase):
    def test_bash_failed_command_attaches_to_open_receipt(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            db_path = repo / "lstack.db"
            con = connect(db_path)
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Hook")
            con.close()
            with _patch_git_bash_env({"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_RECEIPTS": "1"}):
                result = process_hook_payload(_bash_payload("python3 missing.py", 127, "command not found"), cwd=repo)
            con = connect(db_path)
            project = ensure_project(con, repo)
            receipt = get_open_receipt(con, project["id"])
            events = list_receipt_events(con, project["id"], receipt["id"])
            con.close()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(receipt["capture_event_ids"])
        self.assertTrue(any(e["event_type"] == "failed_command" for e in events))

    def test_bash_test_result_attaches_to_open_receipt(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            db_path = repo / "lstack.db"
            con = connect(db_path)
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Hook tests")
            con.close()
            with _patch_git_bash_env({"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_RECEIPTS": "1"}):
                process_hook_payload(_bash_payload("py -3 -m unittest tests -v", 0, "10 passed"), cwd=repo)
            con = connect(db_path)
            project = ensure_project(con, repo)
            receipt = get_open_receipt(con, project["id"])
            con.close()
        self.assertTrue(receipt["tests"])
        self.assertEqual(receipt["tests"][0]["result"], "pass")

    def test_write_implementation_diff_attaches_path_only(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            db_path = repo / "lstack.db"
            con = connect(db_path)
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Hook write")
            con.close()
            target = repo / "file.py"
            payload = _file_payload("Edit", target, {"old_str": "SECRET_TOKEN=abc123", "new_str": "safe"})
            with _patch_git_bash_env({"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_RECEIPTS": "1"}):
                process_hook_payload(payload, cwd=repo)
            con = connect(db_path)
            project = ensure_project(con, repo)
            receipt = get_open_receipt(con, project["id"])
            events = list_receipt_events(con, project["id"], receipt["id"])
            con.close()
        serialized = json.dumps({"receipt": receipt, "events": events})
        self.assertIn("implementation_diff", serialized)
        self.assertIn("file.py", serialized)
        self.assertNotIn("SECRET_TOKEN=abc123", serialized)
        self.assertNotIn("old_str", serialized)
        self.assertNotIn("new_str", serialized)

    def test_no_open_receipt_does_not_crash_or_auto_create_by_default(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            db_path = repo / "lstack.db"
            with _patch_git_bash_env({"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1"}):
                result = process_hook_payload(_file_payload("Write", repo / "x.py"), cwd=repo)
            con = connect(db_path)
            project = ensure_project(con, repo)
            receipt = get_open_receipt(con, project["id"])
            events = list_events(con, project["id"])
            con.close()
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(receipt)
        self.assertGreater(len(events), 0)

    def test_auto_create_requires_explicit_env_and_active_contract(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            db_path = repo / "lstack.db"
            con = connect(db_path)
            project = ensure_project(con, repo)
            create_contract(con, project["id"], task_goal="Auto receipt", allowed_files=["*.py"])
            con.close()
            with _patch_git_bash_env({
                "LSTACK_DB_PATH": str(db_path),
                "LSTACK_BRAIN_AUTO_LEARN": "1",
                "LSTACK_BRAIN_RECEIPTS": "1",
                "LSTACK_BRAIN_RECEIPT_AUTO_CREATE": "1",
            }):
                process_hook_payload(_file_payload("Write", repo / "x.py"), cwd=repo)
            con = connect(db_path)
            project = ensure_project(con, repo)
            receipt = get_open_receipt(con, project["id"])
            con.close()
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["source"], "hook")
        self.assertIsNotNone(receipt["contract_id"])

    def test_receipts_env_zero_disables_attachment(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            db_path = repo / "lstack.db"
            con = connect(db_path)
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Disabled")
            con.close()
            with _patch_git_bash_env({"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_RECEIPTS": "0"}):
                process_hook_payload(_bash_payload("python3 missing.py", 127, "command not found"), cwd=repo)
            con = connect(db_path)
            project = ensure_project(con, repo)
            receipt = get_open_receipt(con, project["id"])
            con.close()
        self.assertEqual(receipt["capture_event_ids"], [])


class TestReceiptHookFailureModes(unittest.TestCase):
    def test_malformed_json_wrapper_exits_zero(self):
        env = os.environ.copy()
        script = ROOT / "scripts" / "lbrain-capture-hook.py"
        proc = subprocess.run(
            [sys.executable, str(script), "post-tool"],
            input="{not valid json",
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("syntax error", (proc.stdout + proc.stderr).lower())


if __name__ == "__main__":
    unittest.main()
