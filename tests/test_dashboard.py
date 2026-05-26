"""Tests for the LStack Dashboard — P0 foundation."""

import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SKILLS = ROOT / "skills"
BIN_LSTACK = ROOT / "bin" / "lstack"
DASHBOARD_BACKEND = ROOT / "dashboard" / "backend"
DASHBOARD_SERVER_SHIM = SCRIPTS / "dashboard_server.py"


def _ensure_path():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _load_overview_mod():
    _ensure_path()
    import importlib
    import dashboard.backend.overview as mod
    importlib.reload(mod)
    return mod


def _load_server_mod():
    _ensure_path()
    import importlib
    import dashboard.backend.server as mod
    importlib.reload(mod)
    return mod


# ---------------------------------------------------------------------------
# JSON overview shape
# ---------------------------------------------------------------------------

class TestDashboardJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mod = _load_overview_mod()
        cls.data = mod.build_dashboard_overview()

    def test_valid_json(self):
        dumped = json.dumps(self.data)
        parsed = json.loads(dumped)
        self.assertIsInstance(parsed, dict)

    def test_schema_version(self):
        self.assertIn("schema_version", self.data)
        self.assertEqual(self.data["schema_version"], 1)

    def test_read_only_flag(self):
        self.assertTrue(self.data.get("read_only"))

    def test_generated_at(self):
        self.assertIn("generated_at", self.data)
        self.assertRegex(self.data["generated_at"], r"\d{4}-\d{2}-\d{2}T")

    def test_project_section(self):
        p = self.data.get("project", {})
        self.assertIn("name", p)
        self.assertIn("root_path_display", p)
        self.assertIn("git_branch", p)

    def test_runtime_section(self):
        rt = self.data.get("runtime", {})
        self.assertIn("os", rt)
        self.assertIn("python_available", rt)
        self.assertIn("git_available", rt)

    def test_install_section(self):
        inst = self.data.get("install", {})
        self.assertIn("claude_dir", inst)
        self.assertIn("settings_exists", inst)
        self.assertIn("settings_valid_json", inst)

    def test_hooks_section(self):
        h = self.data.get("hooks", {})
        self.assertIsInstance(h, dict)

    def test_skills_section(self):
        sk = self.data.get("skills", {})
        self.assertIn("count", sk)
        self.assertIn("items", sk)

    def test_agents_section(self):
        ag = self.data.get("agents", {})
        self.assertIn("count", ag)
        self.assertIn("items", ag)

    def test_memory_section(self):
        m = self.data.get("memory", {})
        self.assertIn("db_reachable", m)
        self.assertIn("observations_count", m)
        self.assertIn("learnings_count", m)

    def test_health_section(self):
        h = self.data.get("health", {})
        self.assertIn("available", h)
        self.assertIn("note", h)
        self.assertNotIn("run", h.get("note", "").lower()[:3])

    def test_parallel_section(self):
        p = self.data.get("parallel", {})
        self.assertIn("available", p)
        self.assertIn("legacy_command", p)

    def test_lbrain_section_present(self):
        self.assertIn("lbrain", self.data)

    def test_doctor_section(self):
        dr = self.data.get("doctor", {})
        self.assertTrue(isinstance(dr, dict))

    def test_actions_section(self):
        ac = self.data.get("actions", {})
        self.assertIn("enabled", ac)
        self.assertIn("items", ac)

    def test_v1_actions_disabled(self):
        ac = self.data.get("actions", {})
        self.assertFalse(ac.get("enabled"), "actions.enabled must be False in V1")
        for item in ac.get("items", []):
            self.assertFalse(item.get("enabled"), f"action {item.get('id')} must be disabled in V1")

    def test_actions_mode_read_only(self):
        ac = self.data.get("actions", {})
        self.assertEqual(ac.get("mode"), "read_only_v1")

    def test_no_hardcoded_user_paths(self):
        dumped = json.dumps(self.data)
        self.assertNotIn("leonard.gunder", dumped)
        self.assertNotIn("/c/Users/Leo/", dumped)

    def test_health_note_no_auto_run(self):
        note = self.data.get("health", {}).get("note", "")
        self.assertIn("not run automatically", note)


class TestDashboardMemoryDetail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db_path = os.environ.get("LSTACK_DB_PATH")
        os.environ["LSTACK_DB_PATH"] = str(Path(self.tmp.name) / "lstack.db")
        self.mod = _load_overview_mod()
        project = str(self.mod.CLAUDE_DIR.resolve()).replace("\\", "/")
        con = sqlite3.connect(os.environ["LSTACK_DB_PATH"])
        con.executescript("""
            CREATE TABLE observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                project TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                project TEXT NOT NULL,
                key TEXT NOT NULL,
                type TEXT NOT NULL,
                insight TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                source TEXT NOT NULL,
                trusted INTEGER NOT NULL DEFAULT 0,
                tags TEXT,
                files_json TEXT,
                branch TEXT,
                commit_sha TEXT,
                supersedes_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        con.execute(
            "INSERT INTO observations (session_id, project, content, tags, created_at) VALUES (?, ?, ?, ?, ?)",
            ("s1", project, "Use Bun for dashboard frontend builds.", "dashboard,bun", "2026-05-25T10:00:00Z"),
        )
        con.execute(
            """
            INSERT INTO learnings (
                session_id, project, key, type, insight, confidence, source, trusted,
                tags, files_json, branch, commit_sha, supersedes_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s2", project, "dashboard-bun-build", "tool",
                "Dashboard frontend verification uses Bun.", 9, "user-stated", 1,
                "dashboard,bun", '["dashboard/frontend/package.json"]',
                "main", "abc123", None, "2026-05-25T11:00:00Z", "2026-05-25T11:00:00Z",
            ),
        )
        con.commit()
        con.close()

    def tearDown(self):
        if self.old_db_path is None:
            os.environ.pop("LSTACK_DB_PATH", None)
        else:
            os.environ["LSTACK_DB_PATH"] = self.old_db_path
        _load_overview_mod()
        self.tmp.cleanup()

    def test_memory_detail_includes_observations_and_learnings(self):
        data = self.mod.build_memory_detail(limit=10)
        self.assertTrue(data["available"])
        self.assertEqual(data["observations_count"], 1)
        self.assertEqual(data["learnings_count"], 1)
        self.assertEqual(data["observations"][0]["content"], "Use Bun for dashboard frontend builds.")
        self.assertEqual(data["observations"][0]["tags"], ["dashboard", "bun"])
        self.assertEqual(data["observations"][0]["scope"], "project")
        self.assertEqual(data["learnings"][0]["key"], "dashboard-bun-build")
        self.assertEqual(data["learnings"][0]["files"], ["dashboard/frontend/package.json"])
        self.assertTrue(data["learnings"][0]["trusted"])


# ---------------------------------------------------------------------------
# Server endpoint tests
# ---------------------------------------------------------------------------

def _find_free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestDashboardServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_path()
        from http.server import HTTPServer
        from dashboard.backend.server import DashboardHandler
        cls.port = _find_free_port()
        cls.server = HTTPServer(("127.0.0.1", cls.port), DashboardHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.read().decode(), r.headers.get("Content-Type", "")

    def _request(self, method, path):
        import urllib.error
        req = urllib.request.Request(self.base + path, method=method, data=b"")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_root_returns_html(self):
        status, body, ct = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn("<html", body)

    def test_root_no_remote_assets(self):
        _, body, _ = self._get("/")
        for cdn in ["cdn.", "googleapis.com", "unpkg.com", "jsdelivr.net", "cloudflare.com"]:
            self.assertNotIn(cdn, body, f"Served HTML contains CDN reference: {cdn}")

    def test_api_overview_valid_json(self):
        status, body, ct = self._get("/api/overview")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ct)
        data = json.loads(body)
        self.assertIn("schema_version", data)

    def test_api_lbrain_valid_json(self):
        status, body, ct = self._get("/api/lbrain")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ct)
        data = json.loads(body)
        self.assertIsInstance(data, dict)

    def test_api_memory_valid_json(self):
        status, body, ct = self._get("/api/memory")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ct)
        data = json.loads(body)
        self.assertIn("observations", data)
        self.assertIn("learnings", data)

    def test_api_health_ok(self):
        status, body, ct = self._get("/api/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("read_only"))

    def test_api_actions_all_disabled(self):
        status, body, ct = self._get("/api/actions")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data.get("enabled"))
        for item in data.get("items", []):
            self.assertFalse(item.get("enabled"))

    def test_unknown_path_404(self):
        status = self._request("GET", "/api/does-not-exist")
        self.assertEqual(status, 404)

    def test_post_returns_405(self):
        status = self._request("POST", "/api/overview")
        self.assertEqual(status, 405)

    def test_put_returns_405(self):
        status = self._request("PUT", "/api/overview")
        self.assertEqual(status, 405)

    def test_patch_returns_405(self):
        status = self._request("PATCH", "/api/overview")
        self.assertEqual(status, 405)

    def test_delete_returns_405(self):
        status = self._request("DELETE", "/api/overview")
        self.assertEqual(status, 405)


# ---------------------------------------------------------------------------
# Security: dashboard source code must not contain forbidden strings
# ---------------------------------------------------------------------------

class TestDashboardSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Concatenate all backend Python sources for scanning
        backend_files = list(DASHBOARD_BACKEND.glob("*.py"))
        cls.source = "\n".join(p.read_text(encoding="utf-8") for p in backend_files)

    def test_no_claude_subprocess(self):
        self.assertNotIn("claude -p", self.source)

    def test_no_git_reset(self):
        self.assertNotIn("git reset", self.source)

    def test_no_git_clean(self):
        self.assertNotIn("git clean", self.source)

    def test_no_git_push(self):
        self.assertNotIn("git push", self.source)

    def test_no_git_commit(self):
        self.assertNotIn("git commit", self.source)

    def test_no_mutation_endpoint(self):
        # Check server.py specifically — schemas.py legitimately documents forbidden routes
        server_source = (DASHBOARD_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertNotIn('path == "/api/run"', server_source)
        self.assertNotIn('path == "/api/command"', server_source)
        self.assertNotIn('path == "/api/git"', server_source)

    def test_no_remote_cdn(self):
        for cdn in ["cdn.", "googleapis.com", "unpkg.com", "jsdelivr.net", "cloudflare.com"]:
            self.assertNotIn(cdn, self.source)

    def test_no_db_writes(self):
        for stmt in ["INSERT INTO", "UPDATE ", "DELETE FROM", "DROP TABLE"]:
            self.assertNotIn(stmt, self.source)

    def test_html_no_remote_assets(self):
        # Backend sources must not reference CDN URLs in any string
        for cdn in ["cdn.", "googleapis.com", "unpkg.com", "jsdelivr.net", "cloudflare.com"]:
            self.assertNotIn(cdn, self.source, f"Backend source contains CDN URL: {cdn}")


# ---------------------------------------------------------------------------
# CLI: bin/lstack dashboard references
# ---------------------------------------------------------------------------

class TestBinLstackDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = BIN_LSTACK.read_text(encoding="utf-8")

    def test_dashboard_json_flag_mentioned(self):
        self.assertIn("--json", self.source)

    def test_dashboard_parallel_flag_mentioned(self):
        self.assertIn("--parallel", self.source)

    def test_dashboard_server_called(self):
        self.assertTrue(
            "dashboard_server.py" in self.source or "dashboard/backend/server.py" in self.source,
            "bin/lstack must reference dashboard backend server",
        )

    def test_old_parallel_script_preserved(self):
        self.assertIn("dashboard.sh", self.source)

    def test_bin_bash_n(self):
        import subprocess
        source = BIN_LSTACK.read_bytes()
        # bash -n reads from stdin when no filename is given
        r = subprocess.run(["bash", "-n"], input=source, capture_output=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr.decode())

    def test_no_hardcoded_user_path(self):
        self.assertNotIn("/c/Users/Leo", self.source)
        self.assertNotIn("C:\\\\Users\\\\Leo", self.source)
        self.assertNotIn("leonard.gunder", self.source)


# ---------------------------------------------------------------------------
# Skills: no direct python3 db.py calls
# ---------------------------------------------------------------------------

SKILL_FILES = list(SKILLS.rglob("SKILL.md"))

FORBIDDEN_DB_PY = [
    r"python3\s+~/\.claude/scripts/db\.py",
    r"python\s+~/\.claude/scripts/db\.py",
]


class TestSkillsNoPythonDbPy(unittest.TestCase):
    def test_all_skills_found(self):
        self.assertGreater(len(SKILL_FILES), 0, "No skill files found")

    def test_no_skill_uses_python3_db_py(self):
        for sf in SKILL_FILES:
            text = sf.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_DB_PY:
                with self.subTest(file=sf.name, pattern=pattern):
                    self.assertIsNone(
                        re.search(pattern, text),
                        f"{sf.relative_to(ROOT)}: must not use direct python3 db.py (use lstack CLI instead)",
                    )


# ---------------------------------------------------------------------------
# Docs: dashboard mentioned correctly
# ---------------------------------------------------------------------------

class TestDocsUpdated(unittest.TestCase):
    def _readme(self):
        return (ROOT / "README.md").read_text(encoding="utf-8")

    def _lbrain_doc(self):
        return (ROOT / "docs" / "lbrain.md").read_text(encoding="utf-8")

    def test_readme_mentions_lstack_dashboard(self):
        self.assertIn("lstack dashboard", self._readme())

    def test_readme_mentions_dashboard_parallel(self):
        self.assertIn("dashboard --parallel", self._readme())

    def test_readme_mentions_dashboard_json(self):
        self.assertIn("dashboard --json", self._readme())

    def test_readme_dashboard_is_local(self):
        readme = self._readme()
        idx = readme.find("lstack dashboard")
        section = readme[idx:idx + 600]
        self.assertTrue(
            "local" in section.lower() or "127.0.0.1" in section or "localhost" in section,
            "README should note dashboard is local",
        )


# ---------------------------------------------------------------------------
# Cross-platform
# ---------------------------------------------------------------------------

class TestCrossPlatform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        backend_files = list(DASHBOARD_BACKEND.glob("*.py"))
        cls.source = "\n".join(p.read_text(encoding="utf-8") for p in backend_files)

    def test_dashboard_no_hardcoded_c_drive(self):
        self.assertNotIn("C:\\\\", self.source)
        self.assertNotIn("/c/Users/Leo", self.source)

    def test_dashboard_uses_path_home(self):
        self.assertIn("Path.home()", self.source)

    def test_overview_project_has_display_path(self):
        mod = _load_overview_mod()
        data = mod.build_dashboard_overview()
        root = data.get("project", {}).get("root_path_display", "")
        self.assertIsInstance(root, str)
        self.assertGreater(len(root), 0)


if __name__ == "__main__":
    unittest.main()
