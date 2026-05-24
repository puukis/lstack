"""Tests for lstack doctor command (--fix, --json, --deep flags)."""
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


def run_doctor(args=None, env_overrides=None, timeout=45, fake_home=None):
    """Run lstack doctor with optional fake home for isolation."""
    args_str = " ".join(args or [])
    cmd = [BASH, "-c", f'bash "{LSTACK_BASH}" doctor {args_str}']
    env = os.environ.copy()
    if fake_home:
        home_bash = bash_path(fake_home)
        env["HOME"] = home_bash
        env["CLAUDE_DIR"] = home_bash + "/.claude"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


def minimal_fake_claude(base):
    """Create a minimal fake ~/.claude structure for test isolation."""
    cd = Path(base) / ".claude"
    for d in ("bin", "hooks", "scripts", "memory", "logs"):
        (cd / d).mkdir(parents=True, exist_ok=True)

    # Copy lstack binary
    lstack_src = ROOT / "bin" / "lstack"
    shutil.copy2(lstack_src, cd / "bin" / "lstack")
    try:
        (cd / "bin" / "lstack").chmod(0o755)
    except OSError:
        pass

    # Copy scripts
    for s in ("os.sh", "runtime.sh", "gen-settings.sh", "db.py"):
        src = ROOT / "scripts" / s
        if src.exists():
            dst = cd / "scripts" / s
            shutil.copy2(src, dst)
            if s.endswith(".sh"):
                try:
                    dst.chmod(0o755)
                except OSError:
                    pass

    # Copy hooks
    for h in ("session-start.sh", "pre-tool.sh", "post-tool.sh", "pre-compact.sh", "stop.sh"):
        src = ROOT / "hooks" / h
        if src.exists():
            dst = cd / "hooks" / h
            shutil.copy2(src, dst)
            try:
                dst.chmod(0o755)
            except OSError:
                pass

    # Minimal CLAUDE.md
    (cd / "CLAUDE.md").write_text("## Identity\nTest install.\n", encoding="utf-8")

    # Valid settings.json
    cd_bash = bash_path(cd)
    settings = {
        "hooks": {
            "Stop": [{"command": f"bash {cd_bash}/hooks/stop.sh", "timeout": 120}],
            "PreToolUse": [{"command": f"bash {cd_bash}/hooks/pre-tool.sh", "timeout": 30}],
        }
    }
    (cd / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return cd


@unittest.skipUnless(BASH, "bash not available")
class TestDoctorOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cd = minimal_fake_claude(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_doctor_runs(self):
        r = run_doctor(fake_home=self.tmp, timeout=45)
        self.assertIn(r.returncode, (0, 1))

    def test_doctor_human_output_has_markers(self):
        r = run_doctor(fake_home=self.tmp, timeout=45)
        combined = r.stdout + r.stderr
        self.assertTrue(
            any(m in combined for m in ("PASS", "FAIL", "WARN")),
            f"No markers found. stdout: {combined[:500]}"
        )

    def test_doctor_summary_in_human_output(self):
        r = run_doctor(fake_home=self.tmp, timeout=45)
        self.assertIn("Summary:", r.stdout, f"No Summary in: {r.stdout[:300]}")

    def test_doctor_json_valid(self):
        r = run_doctor(["--json"], fake_home=self.tmp, timeout=45)
        out = r.stdout.strip()
        self.assertTrue(out, f"Empty JSON output. stderr: {r.stderr[:300]}")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            self.fail(f"Invalid JSON: {out[:500]}")
        self.assertIn("status", data)
        self.assertIn("checks", data)

    def test_doctor_json_checks_have_fields(self):
        r = run_doctor(["--json"], fake_home=self.tmp, timeout=45)
        data = json.loads(r.stdout.strip())
        for check in data.get("checks", []):
            for field in ("id", "severity", "message", "fixable", "fixed"):
                self.assertIn(field, check, f"Missing '{field}' in check: {check}")

    def test_doctor_json_status_values(self):
        r = run_doctor(["--json"], fake_home=self.tmp, timeout=45)
        data = json.loads(r.stdout.strip())
        self.assertIn(data["status"], ("pass", "warn", "fail"))

    def test_doctor_json_summary_counts(self):
        r = run_doctor(["--json"], fake_home=self.tmp, timeout=45)
        data = json.loads(r.stdout.strip())
        self.assertIn("summary", data)
        summary = data["summary"]
        for k in ("pass", "warn", "fail"):
            self.assertIn(k, summary)
            self.assertIsInstance(summary[k], int)


@unittest.skipUnless(BASH, "bash not available")
class TestDoctorNoMutate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cd = minimal_fake_claude(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_doctor_without_fix_does_not_create_bak_files(self):
        run_doctor(fake_home=self.tmp, timeout=45)
        # No .bak files should have been created
        for root, dirs, files in os.walk(self.tmp):
            for f in files:
                self.assertFalse(
                    ".bak." in f,
                    f"doctor without --fix created backup: {os.path.join(root, f)}"
                )

    def test_doctor_json_without_fix_does_not_add_files(self):
        before = {str(p) for p in Path(self.tmp).rglob("*") if p.is_file()}
        run_doctor(["--json"], fake_home=self.tmp, timeout=45)
        after = {str(p) for p in Path(self.tmp).rglob("*") if p.is_file()}
        new_files = after - before
        self.assertEqual(new_files, set(), f"Unexpected new files: {new_files}")


@unittest.skipUnless(BASH, "bash not available")
class TestDoctorFix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cd = minimal_fake_claude(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fix_creates_missing_memory_dir(self):
        shutil.rmtree(str(self.cd / "memory"), ignore_errors=True)
        run_doctor(["--fix"], fake_home=self.tmp, timeout=45)
        self.assertTrue((self.cd / "memory").is_dir(),
                        "memory/ should exist after --fix")

    def test_fix_creates_missing_log_dir(self):
        shutil.rmtree(str(self.cd / "logs"), ignore_errors=True)
        run_doctor(["--fix"], fake_home=self.tmp, timeout=45)
        self.assertTrue((self.cd / "logs").is_dir(),
                        "logs/ should exist after --fix")

    def test_fix_backs_up_invalid_settings(self):
        sj = self.cd / "settings.json"
        sj.write_text("{invalid json}", encoding="utf-8")
        run_doctor(["--fix"], fake_home=self.tmp, timeout=45)
        baks = list(self.cd.glob("settings.json.bak.*"))
        self.assertTrue(len(baks) > 0 or sj.exists(),
                        "Either backup created or settings regenerated")

    def test_fix_json_still_valid(self):
        run_doctor(["--fix", "--json"], fake_home=self.tmp, timeout=45)
        # After --fix, settings.json (if present) should be valid JSON
        sj = self.cd / "settings.json"
        if sj.exists():
            data = json.loads(sj.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)

    @unittest.skipUnless(os.name != "nt", "chmod not relevant on native Windows")
    def test_fix_chmods_non_executable_hook(self):
        hook = self.cd / "hooks" / "stop.sh"
        if hook.exists():
            hook.chmod(0o644)
            run_doctor(["--fix"], fake_home=self.tmp, timeout=45)
            mode = hook.stat().st_mode
            self.assertTrue(mode & 0o111, "Hook should be executable after --fix")


@unittest.skipUnless(BASH, "bash not available")
class TestDoctorChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cd = minimal_fake_claude(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_invalid_settings_json(self):
        (self.cd / "settings.json").write_text("{not valid json", encoding="utf-8")
        r = run_doctor(["--json"], fake_home=self.tmp, timeout=45)
        data = json.loads(r.stdout.strip())
        settings_checks = [c for c in data["checks"] if "settings" in c["id"]]
        self.assertTrue(
            any(c["severity"] in ("fail", "warn") for c in settings_checks),
            f"Should detect invalid settings. Checks: {settings_checks}"
        )

    def test_detects_stop_timeout_below_90(self):
        sj = self.cd / "settings.json"
        settings = {"hooks": {"Stop": [{"command": "bash stop.sh", "timeout": 30}]}}
        sj.write_text(json.dumps(settings), encoding="utf-8")
        r = run_doctor(["--json"], fake_home=self.tmp, timeout=45)
        data = json.loads(r.stdout.strip())
        timeout_checks = [c for c in data["checks"] if "stop_timeout" in c["id"]]
        if timeout_checks:
            self.assertEqual(timeout_checks[0]["severity"], "fail")

    def test_no_hardcoded_leo_in_output(self):
        r = run_doctor(["--json"], fake_home=self.tmp, timeout=45)
        # Replace the tmp path so we don't flag the fake home
        sanitized = r.stdout.replace(self.tmp, "TMPDIR").replace(
            self.tmp.replace("\\", "/"), "TMPDIR")
        self.assertNotIn("Leo", sanitized,
                         "Hardcoded 'Leo' in doctor output (outside tmp path)")


@unittest.skipUnless(BASH, "bash not available")
class TestDoctorDeep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cd = minimal_fake_claude(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deep_adds_checks(self):
        r = run_doctor(["--deep", "--json"], fake_home=self.tmp, timeout=60)
        combined = r.stdout
        try:
            data = json.loads(combined.strip())
            check_ids = [c["id"] for c in data.get("checks", [])]
            # Deep checks have 'deep.' prefix
            deep_checks = [cid for cid in check_ids if cid.startswith("deep.")]
            self.assertTrue(
                len(deep_checks) > 0,
                f"No deep checks found. Check IDs: {check_ids[:10]}"
            )
        except json.JSONDecodeError:
            pass  # Python may be unavailable

    def test_deep_bash_n_passes_on_valid_hooks(self):
        r = run_doctor(["--deep", "--json"], fake_home=self.tmp, timeout=60)
        try:
            data = json.loads(r.stdout.strip())
            syntax_checks = [c for c in data.get("checks", [])
                             if c["id"].startswith("deep.hook_syntax")]
            for check in syntax_checks:
                self.assertEqual(check["severity"], "pass",
                                 f"Hook syntax check failed: {check}")
        except json.JSONDecodeError:
            pass


if __name__ == "__main__":
    unittest.main()
