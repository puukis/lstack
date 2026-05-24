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
from brain.decisions import add_decision, seed_lstack_default_decisions
from brain.project import is_lstack_project, lstack_project_signals


class TestBrainGeneralization(unittest.TestCase):
    def test_random_repo_gets_no_lstack_specific_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest"}, "packageManager": "npm@10.0.0"}),
                encoding="utf-8",
            )
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            seeded = seed_lstack_default_decisions(con, project)
            add_decision(
                con,
                project["id"],
                key="runtime-python-provider",
                title="Use lstack runtime for Python execution",
                decision="All lstack production scripts and hooks must use the runtime Python provider.",
                applies_to=["bin/lstack", "hooks/pre-compact.sh"],
                source="detected",
                confidence=10,
            )
            text = build_context(con, project, target="codex")
            explained = build_context(con, project, target="codex", explain=True)
            con.close()
            self.assertEqual(seeded, [])
            self.assertNotIn("runtime-python-provider", text)
            self.assertNotIn("bin/lstack", text)
            self.assertNotIn("hooks/pre-compact.sh", text)
            self.assertNotIn("claude -p", text)
            self.assertNotIn("this lstack task", text)
            self.assertIn("lstack-specific detected decision is not active outside the lstack repo", explained)

    def test_lstack_repo_detection_requires_multiple_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# lstack\n\nlstack for Claude Code.\n", encoding="utf-8")
            self.assertFalse(is_lstack_project(root))
            (root / "bin").mkdir()
            (root / "bin" / "lstack").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "lbrain").mkdir()
            (root / "lbrain" / "brain.py").write_text("# lbrain\n", encoding="utf-8")
            self.assertTrue(is_lstack_project(root))
            self.assertGreaterEqual(len(lstack_project_signals(root)), 2)

    def test_lstack_repo_may_seed_lstack_project_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("lstack is a portable environment for Claude Code.\n", encoding="utf-8")
            (root / "bin").mkdir()
            (root / "bin" / "lstack").write_text("run_python ok\n", encoding="utf-8")
            (root / "lbrain").mkdir()
            (root / "lbrain" / "brain.py").write_text("# lbrain\n", encoding="utf-8")
            (root / "scripts").mkdir()
            (root / "scripts" / "os.sh").write_text("py -3\n", encoding="utf-8")
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            seeded = seed_lstack_default_decisions(con, project)
            text = build_context(con, project, target="codex")
            con.close()
            self.assertTrue(any(item["key"] == "runtime-python-provider" for item in seeded))
            self.assertIn("runtime Python provider", text)

    def test_templates_and_test_fixtures_are_inactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            add_decision(
                con,
                project["id"],
                key="template-package-manager",
                title="Use detected package manager",
                decision="Use the detected package manager consistently.",
                source="template",
                scope="template",
                status="active",
            )
            add_decision(
                con,
                project["id"],
                key="fixture-no-claude",
                title="Fixture",
                decision="Lifecycle hooks must not call claude -p by default.",
                source="test",
                scope="test-fixture",
                status="active",
            )
            text = build_context(con, project, target="codex")
            explained = build_context(con, project, target="codex", explain=True)
            con.close()
            self.assertNotIn("Use the detected package manager consistently", text)
            self.assertNotIn("claude -p", text)
            self.assertIn("template decisions are inactive examples", explained)
            self.assertIn("test fixture decisions are excluded", explained)

    def test_user_global_requires_explicit_source_and_can_be_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            with self.assertRaises(ValueError):
                add_decision(
                    con,
                    None,
                    key="prefer-pnpm",
                    title="Prefer pnpm",
                    decision="Prefer pnpm unless a repo says otherwise.",
                    scope="user-global",
                    source="template",
                )
            add_decision(
                con,
                None,
                key="ask-before-lockfiles",
                title="Ask before lockfiles",
                decision="Ask before editing lockfiles.",
                scope="user-global",
                source="user",
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertIn("Ask before editing lockfiles", text)

    def test_git_bash_user_correction_is_generic_not_lstack_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            from brain.capture import record_event

            result = record_event(
                con,
                project["id"],
                "user_correction",
                "On Windows, I use Git Bash, not WSL.",
                source="user",
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertEqual(result["candidate"]["status"], "promoted")
            self.assertIn("prefer Git Bash", text)
            self.assertNotIn("bin/lstack", text)
            self.assertNotIn("hooks/*.sh", text)

    def test_project_scoping_excludes_other_project_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_a_root = root / "a"
            project_b_root = root / "b"
            project_a_root.mkdir()
            project_b_root.mkdir()
            db_path = root / "lstack.db"
            con = connect(db_path)
            project_a = ensure_project(con, project_a_root)
            project_b = ensure_project(con, project_b_root)
            add_attempt(
                con,
                project_a["id"],
                "Tried yarn install",
                command="yarn install",
                why_failed="Project A uses npm.",
                retry_policy="ask",
                confidence=9,
            )
            add_decision(
                con,
                project_a["id"],
                key="project-a-only",
                title="Project A only",
                decision="Only Project A should see this.",
            )
            text = build_context(con, project_b, target="codex")
            con.close()
            self.assertNotIn("Tried yarn install", text)
            self.assertNotIn("Only Project A should see this", text)

    def test_pending_candidate_explain_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            upsert_candidate(
                con,
                project["id"],
                "implementation_decision",
                "pending-example",
                "Pending example",
                "Pending candidate body.",
                proposed_target="brain_decisions",
                confidence=7,
            )
            text = build_context(con, project, target="codex")
            explained = build_context(con, project, target="codex", explain=True)
            con.close()
            self.assertNotIn("Pending candidate body", text)
            self.assertIn("pending memory candidates are excluded", explained)


if __name__ == "__main__":
    unittest.main()
