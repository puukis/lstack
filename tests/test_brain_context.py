import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.attempts import add_attempt
from brain.capture import upsert_candidate
from brain.context import build_context
from brain.db import connect, ensure_project
from brain.decisions import add_decision, disable_decision
from brain.passport import get_or_refresh_passport


class TestBrainContext(unittest.TestCase):
    def test_context_includes_passport_attempts_and_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest"}, "packageManager": "pnpm@9.0.0"}),
                encoding="utf-8",
            )
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            get_or_refresh_passport(con, project, refresh=True)
            add_attempt(
                con,
                project["id"],
                "Tried npm install",
                command="npm install",
                why_failed="Repo uses pnpm",
                replacement_approach="Use pnpm",
                retry_policy="ask",
                confidence=9,
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertIn("Platform:", text)
            self.assertIn("Package manager: pnpm", text)
            self.assertIn("Avoid repeating", text)
            self.assertIn("Use pnpm", text)

    def test_context_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            add_attempt(
                con,
                project["id"],
                "Secret command",
                command="GITHUB_TOKEN=ghp_fakefakefake run",
                retry_policy="ask",
                confidence=9,
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertNotIn("ghp_fakefakefake", text)
            self.assertIn("<redacted>", text)

    def test_json_context_valid_and_explain_has_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            data = build_context(con, project, target="chatgpt", explain=True, json_mode=True)
            con.close()
            json.dumps(data)
            self.assertIn("included", data)
            self.assertTrue(data["explain"])
            self.assertIn("reason", data["explain"][0])

    def test_active_decisions_included_and_pending_candidates_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            add_decision(
                con,
                project["id"],
                key="runtime-python-provider",
                title="Use lstack runtime for Python execution",
                decision="Use run_python instead of direct python/python3 calls.",
                forbidden_patterns=["python3 ", "python "],
                required_patterns=["run_python"],
                applies_to=["scripts/*.sh"],
                confidence=10,
            )
            upsert_candidate(
                con,
                project["id"],
                "implementation_decision",
                "maybe-style",
                "Maybe style",
                "Possible code style preference.",
                confidence=6,
                proposed_target="brain_decisions",
            )
            normal = build_context(con, project, target="codex")
            explained = build_context(con, project, target="codex", explain=True)
            data = build_context(con, project, target="claude", json_mode=True)
            disable_decision(con, project["id"], "runtime-python-provider")
            disabled = build_context(con, project, target="codex")
            con.close()
            self.assertIn("Implementation decisions:", normal)
            self.assertIn("Use run_python", normal)
            self.assertNotIn("Possible code style preference", normal)
            self.assertIn("pending memory candidates are excluded", explained)
            self.assertTrue(any(item.get("key") == "runtime-python-provider" for item in data["included"]))
            self.assertNotIn("Use run_python", disabled)

    def test_context_redacts_decision_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            add_decision(
                con,
                project["id"],
                key="secret-decision",
                title="Secret decision",
                decision="Do not use GITHUB_TOKEN=ghp_fakefakefake in examples.",
                confidence=8,
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertIn("<redacted>", text)
            self.assertNotIn("ghp_fakefakefake", text)


if __name__ == "__main__":
    unittest.main()
