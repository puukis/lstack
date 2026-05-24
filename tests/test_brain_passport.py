import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.db import connect, ensure_project
from brain.passport import detect_package_manager, detect_passport, get_or_refresh_passport, save_passport


class TestBrainPassport(unittest.TestCase):
    def write_json(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_detects_package_manager_from_lockfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")
            result = detect_package_manager(root)
            self.assertEqual(result["package_manager"], "pnpm")

    def test_detects_package_manager_from_package_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_json(root / "package.json", {"packageManager": "yarn@4.0.0"})
            (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")
            result = detect_package_manager(root)
            self.assertEqual(result["package_manager"], "yarn")
            self.assertTrue(result["conflicts"])

    def test_reports_lockfile_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")
            (root / "package-lock.json").write_text("", encoding="utf-8")
            result = detect_package_manager(root)
            self.assertEqual(result["package_manager"], "pnpm")
            self.assertEqual(result["conflicts"][0]["type"], "multiple-lockfiles")

    def test_detects_scripts_node_typescript_python_and_generated_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_json(
                root / "package.json",
                {"scripts": {"test": "vitest", "build": "tsc", "typecheck": "tsc --noEmit"}},
            )
            (root / "tsconfig.json").write_text("{}", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "src").mkdir()
            passport = detect_passport(root, {"name": "repo"})
            self.assertIn("Node", passport["stack"])
            self.assertIn("TypeScript", passport["stack"])
            self.assertIn("Python", passport["stack"])
            self.assertIn("test", passport["commands"]["scripts"])
            self.assertIn("node_modules", passport["paths"]["generated_folders"])

    def test_preserves_manual_overrides_on_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = Path(tmp) / "lstack.db"
            self.write_json(root / "package.json", {"scripts": {"test": "node test.js"}})
            con = connect(db_path)
            project = ensure_project(con, root)
            first = save_passport(con, project, detect_passport(root, project))
            con.execute(
                "UPDATE brain_passports SET manual_overrides_json = ? WHERE id = ?",
                (json.dumps({"test": "override"}), first["id"]),
            )
            con.commit()
            refreshed = get_or_refresh_passport(con, project, refresh=True)
            con.close()
            self.assertEqual(refreshed["manual_overrides"], {"test": "override"})

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            passport = detect_passport(root, {"name": "repo"})
            json.dumps(passport)


if __name__ == "__main__":
    unittest.main()

