"""Context integration tests for LBrain Change Receipts."""

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

from brain.context import build_context
from brain.db import connect, ensure_project
from brain.receipts import finalize_receipt, start_receipt


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


@unittest.skipUnless(shutil.which("git"), "git not available")
class TestReceiptContext(unittest.TestCase):
    def test_open_receipt_appears_in_context_for_claude(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Open receipt", goal="Track context")
            text = build_context(con, project, target="claude")
            con.close()
        self.assertIn("Open change receipt", text)
        self.assertIn("Open receipt", text)

    def test_finalized_receipt_does_not_spam_normal_context(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            receipt = start_receipt(con, project, title="Finalized receipt")
            finalize_receipt(con, project, receipt["id"], summary="Done")
            text = build_context(con, project, target="claude")
            con.close()
        self.assertNotIn("Open change receipt", text)
        self.assertNotIn("Finalized receipt", text)

    def test_debug_context_shows_receipt_metadata(self):
        with tempfile.TemporaryDirectory() as tmp, _patch_git_bash_env():
            repo = _make_repo(tmp)
            con = connect(repo / "lstack.db")
            project = ensure_project(con, repo)
            start_receipt(con, project, title="Debug receipt")
            text = build_context(con, project, target="claude", debug=True)
            con.close()
        self.assertIn("Base/head", text)
        self.assertIn("Attached events", text)

    def test_unrelated_project_receipt_does_not_leak(self):
        with tempfile.TemporaryDirectory() as db_tmp:
            db_path = Path(db_tmp) / "lstack.db"
            with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b, _patch_git_bash_env():
                repo_a = _make_repo(tmp_a)
                repo_b = _make_repo(tmp_b)
                con = connect(db_path)
                project_a = ensure_project(con, repo_a)
                project_b = ensure_project(con, repo_b)
                start_receipt(con, project_a, title="Project A receipt")
                text_b = build_context(con, project_b, target="claude")
                con.close()
        self.assertNotIn("Project A receipt", text_b)


if __name__ == "__main__":
    unittest.main()
