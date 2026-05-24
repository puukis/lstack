import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.context import build_context
from brain.db import connect, ensure_project
from brain.decisions import (
    add_decision,
    check_decisions,
    disable_decision,
    get_decision,
    list_decisions,
    search_decisions,
)


class TestBrainDecisions(unittest.TestCase):
    def make_db(self, root):
        con = connect(Path(root) / "lstack.db")
        project = ensure_project(con, root)
        return con, project

    def add_runtime_decision(self, con, project):
        return add_decision(
            con,
            project["id"],
            key="runtime-python-provider",
            title="Use lstack runtime for Python execution",
            decision="Use run_python instead of direct python/python3 calls.",
            rationale="Windows Git Bash may only have py -3.",
            enforcement_hint="Scan scripts for direct python calls.",
            forbidden_patterns=["python3 ", "python "],
            required_patterns=["run_python"],
            applies_to=["scripts/*.sh"],
            confidence=10,
        )

    def test_add_list_show_search_and_duplicate_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            first = self.add_runtime_decision(con, project)
            updated = add_decision(
                con,
                project["id"],
                key="runtime-python-provider",
                title="Use runtime Python",
                decision="Use run_python.",
                confidence=9,
            )
            items = list_decisions(con, project["id"])
            found = search_decisions(con, project["id"], "runtime")
            shown = get_decision(con, project["id"], "runtime-python-provider")
            con.close()
            self.assertEqual(first["id"], updated["id"])
            self.assertEqual(len(items), 1)
            self.assertEqual(shown["title"], "Use runtime Python")
            self.assertEqual(found[0]["key"], "runtime-python-provider")

    def test_check_detects_forbidden_pattern_and_redacts_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "run.sh").write_text(
                "run_python ok\npython3 tool.py GITHUB_TOKEN=ghp_fakefakefake\n",
                encoding="utf-8",
            )
            con, project = self.make_db(root)
            self.add_runtime_decision(con, project)
            result = check_decisions(con, project)
            con.close()
            json.dumps(result)
            self.assertEqual(result["violation_count"], 1)
            self.assertIn("<redacted>", result["violations"][0]["line_redacted"])
            self.assertNotIn("ghp_fakefakefake", result["violations"][0]["line_redacted"])

    def test_check_handles_missing_globs_and_ignores_generated_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "node_modules").mkdir()
            (root / "node_modules" / "bad.sh").write_text("python3 generated.py\n", encoding="utf-8")
            con, project = self.make_db(root)
            add_decision(
                con,
                project["id"],
                key="generated-skip",
                title="Skip generated folders",
                decision="Generated folders should not produce decision violations.",
                forbidden_patterns=["python3 "],
                applies_to=["node_modules/*.sh", "missing/*.sh"],
                confidence=8,
            )
            result = check_decisions(con, project)
            con.close()
            self.assertEqual(result["violation_count"], 0)
            self.assertTrue(result["missing_paths"])
            self.assertIn("node_modules/bad.sh", result["skipped_generated_files"])

    def test_disable_removes_decision_from_normal_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            self.add_runtime_decision(con, project)
            text = build_context(con, project, target="codex")
            self.assertIn("Use run_python", text)
            disable_decision(con, project["id"], "runtime-python-provider")
            text = build_context(con, project, target="codex")
            explained = build_context(con, project, target="codex", explain=True)
            con.close()
            self.assertNotIn("Use run_python instead", text)
            self.assertIn("disabled decisions are excluded", explained)


if __name__ == "__main__":
    unittest.main()
