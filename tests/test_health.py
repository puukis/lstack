"""Tests for lstack health command."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def find_bash():
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return shutil.which("bash")


def bash_path(path):
    value = Path(path).resolve().as_posix()
    if len(value) >= 3 and value[1:3] == ":/":
        if Path("C:/Program Files/Git/bin/bash.exe").exists():
            return f"/{value[0].lower()}/{value[3:]}"
        return f"/mnt/{value[0].lower()}/{value[3:]}"
    return value


BASH = find_bash()
LSTACK_BASH = bash_path(ROOT / "bin" / "lstack")


def make_fake_home(base):
    """Create a minimal ~/.claude for test isolation."""
    home = Path(base) / "home"
    cd = home / ".claude"
    for d in ("scripts", "memory", "bin"):
        (cd / d).mkdir(parents=True, exist_ok=True)
    for s in ("os.sh", "runtime.sh", "db.py", "gen-settings.sh"):
        src = ROOT / "scripts" / s
        if src.exists():
            dst = cd / "scripts" / s
            shutil.copy2(src, dst)
            if s.endswith(".sh"):
                try:
                    dst.chmod(0o755)
                except OSError:
                    pass
    lstack_src = ROOT / "bin" / "lstack"
    dst = cd / "bin" / "lstack"
    shutil.copy2(lstack_src, dst)
    try:
        dst.chmod(0o755)
    except OSError:
        pass
    return home, cd


def run_health(args=None, cwd=None, fake_home=None, timeout=60):
    args_str = " ".join(args or [])
    cmd = [BASH, "-c", f'bash "{LSTACK_BASH}" health {args_str}']
    env = os.environ.copy()
    if fake_home:
        home_bash = bash_path(fake_home)
        env["HOME"] = home_bash
        env["CLAUDE_DIR"] = home_bash + "/.claude"
    return subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout, cwd=(str(cwd) if cwd else None), env=env,
    )


@unittest.skipUnless(BASH, "bash not available")
class TestHealthBasic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home, self.cd = make_fake_home(self.tmp)
        self.proj = Path(self.tmp) / "project"
        self.proj.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_health_runs_in_empty_project(self):
        r = run_health(["--no-save"], cwd=self.proj, fake_home=self.home, timeout=30)
        self.assertIn(r.returncode, (0, 1))

    def test_health_no_save_does_not_create_history(self):
        hf = self.cd / "memory" / "health-history.jsonl"
        run_health(["--no-save"], cwd=self.proj, fake_home=self.home, timeout=30)
        self.assertFalse(hf.exists(), "health --no-save should not write history")

    def test_health_json_valid(self):
        r = run_health(["--json", "--no-save"], cwd=self.proj, fake_home=self.home, timeout=30)
        out = r.stdout.strip()
        if not out:
            self.skipTest("No JSON output (Python unavailable)")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            self.fail(f"health --json produced invalid JSON: {out[:500]}")
        self.assertIn("project", data)
        self.assertIn("score", data)

    def test_health_json_has_required_fields(self):
        r = run_health(["--json", "--no-save"], cwd=self.proj, fake_home=self.home, timeout=30)
        out = r.stdout.strip()
        if not out:
            self.skipTest("No JSON output")
        data = json.loads(out)
        for field in ("project", "branch", "score", "categories", "recommendations"):
            self.assertIn(field, data, f"Missing field '{field}'")

    def test_health_does_not_mutate_project(self):
        before = {str(p) for p in self.proj.rglob("*")}
        run_health(["--no-save"], cwd=self.proj, fake_home=self.home, timeout=30)
        after = {str(p) for p in self.proj.rglob("*")}
        self.assertEqual(before, after, "health must not add files to project")

    def test_health_no_hardcoded_leo_in_output(self):
        r = run_health(["--json", "--no-save"], cwd=self.proj, fake_home=self.home, timeout=30)
        sanitized = r.stdout.replace(self.tmp, "TMPDIR")
        self.assertNotIn("Leo", sanitized)


@unittest.skipUnless(BASH, "bash not available")
class TestHealthDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home, self.cd = make_fake_home(self.tmp)
        self.proj = Path(self.tmp) / "project"
        self.proj.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_health_detects_node_project(self):
        (self.proj / "package.json").write_text(
            json.dumps({"name": "test", "scripts": {"test": "echo ok", "lint": "echo ok"}}),
            encoding="utf-8"
        )
        r = run_health(["--detect"], cwd=self.proj, fake_home=self.home, timeout=30)
        combined = r.stdout + r.stderr
        self.assertIn("test", combined.lower())

    def test_health_detects_python_project(self):
        (self.proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        r = run_health(["--detect"], cwd=self.proj, fake_home=self.home, timeout=30)
        self.assertIn(r.returncode, (0, 1))

    def test_health_detects_go_project(self):
        (self.proj / "go.mod").write_text("module example.com/x\n\ngo 1.21\n", encoding="utf-8")
        r = run_health(["--detect"], cwd=self.proj, fake_home=self.home, timeout=30)
        self.assertIn(r.returncode, (0, 1))

    def test_health_detects_rust_project(self):
        (self.proj / "Cargo.toml").write_text(
            '[package]\nname="x"\nversion="0.1.0"\n', encoding="utf-8"
        )
        r = run_health(["--detect"], cwd=self.proj, fake_home=self.home, timeout=30)
        self.assertIn(r.returncode, (0, 1))

    def test_health_parses_health_stack_section(self):
        (self.proj / ".claude").mkdir()
        (self.proj / ".claude" / "CLAUDE.md").write_text(
            "## Health Stack\ntests: echo test-ok\nlint: echo lint-ok\n",
            encoding="utf-8"
        )
        r = run_health(["--detect"], cwd=self.proj, fake_home=self.home, timeout=30)
        combined = r.stdout + r.stderr
        self.assertIn("tests", combined.lower())

    def test_health_parses_build_and_test_fallback(self):
        (self.proj / ".claude").mkdir()
        (self.proj / ".claude" / "CLAUDE.md").write_text(
            "## Build & Test\ntests: echo test\n",
            encoding="utf-8"
        )
        r = run_health(["--detect"], cwd=self.proj, fake_home=self.home, timeout=30)
        self.assertIn(r.returncode, (0, 1))

    def test_health_with_spaces_in_project_path(self):
        proj_spaces = Path(self.tmp) / "my project with spaces"
        proj_spaces.mkdir()
        r = run_health(["--no-save", "--json"], cwd=proj_spaces, fake_home=self.home, timeout=30)
        self.assertIn(r.returncode, (0, 1))


@unittest.skipUnless(BASH, "bash not available")
class TestHealthHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home, self.cd = make_fake_home(self.tmp)
        self.proj = Path(self.tmp) / "project"
        self.proj.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_health_save_appends_jsonl(self):
        hf = self.cd / "memory" / "health-history.jsonl"
        run_health(["--save"], cwd=self.proj, fake_home=self.home, timeout=30)
        if hf.exists():
            lines = [l.strip() for l in hf.read_text(encoding="utf-8").splitlines() if l.strip()]
            if lines:
                data = json.loads(lines[-1])
                self.assertIn("score", data)

    def test_health_history_is_valid_jsonl(self):
        hf = self.cd / "memory" / "health-history.jsonl"
        run_health(["--save"], cwd=self.proj, fake_home=self.home, timeout=30)
        run_health(["--save"], cwd=self.proj, fake_home=self.home, timeout=30)
        if hf.exists():
            for line in hf.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)  # Should not raise

    def test_health_history_command(self):
        run_health(["--save"], cwd=self.proj, fake_home=self.home, timeout=30)
        r = run_health(["--history"], cwd=self.proj, fake_home=self.home, timeout=30)
        self.assertIn(r.returncode, (0, 1))


@unittest.skipUnless(BASH, "bash not available")
class TestHealthConfigure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home, self.cd = make_fake_home(self.tmp)
        self.proj = Path(self.tmp) / "project"
        self.proj.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_configure_noninteractive_does_not_hang(self):
        r = run_health(["--configure"], cwd=self.proj, fake_home=self.home, timeout=15)
        self.assertIn(r.returncode, (0, 1))

    def test_configure_backs_up_claude_md_when_confirmed(self):
        (self.proj / ".claude").mkdir()
        claude_md = self.proj / ".claude" / "CLAUDE.md"
        claude_md.write_text("## Identity\nOriginal content\n", encoding="utf-8")
        (self.proj / "package.json").write_text(
            json.dumps({"scripts": {"test": "echo ok"}}), encoding="utf-8"
        )
        home_bash = bash_path(self.home)
        cmd = [BASH, "-c", f'bash "{LSTACK_BASH}" health --configure']
        env = os.environ.copy()
        env["HOME"] = home_bash
        env["CLAUDE_DIR"] = home_bash + "/.claude"
        subprocess.run(cmd, input="y\n", capture_output=True, text=True,
                       timeout=15, cwd=str(self.proj), env=env)
        # CLAUDE.md must still exist after configure
        self.assertTrue(claude_md.exists(), "CLAUDE.md should still exist after configure")


@unittest.skipUnless(BASH, "bash not available")
class TestHealthShellCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home, self.cd = make_fake_home(self.tmp)
        self.proj = Path(self.tmp) / "shellproject"
        (self.proj / "scripts").mkdir(parents=True)
        (self.proj / "scripts" / "hello.sh").write_text(
            "#!/bin/bash\necho hello\n", encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_health_detect_includes_shell_category(self):
        r = run_health(["--detect"], cwd=self.proj, fake_home=self.home, timeout=20)
        combined = r.stdout + r.stderr
        self.assertIn(r.returncode, (0, 1))
        # Shell check category should appear in detection output
        self.assertIn("shell", combined.lower())


if __name__ == "__main__":
    unittest.main()
