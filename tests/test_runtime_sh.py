"""Tests for scripts/runtime.sh cross-platform runtime layer."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SH = ROOT / "scripts" / "runtime.sh"
OS_SH = ROOT / "scripts" / "os.sh"


def find_bash():
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return shutil.which("bash")


def bash_path(path):
    """Convert a native path to one the detected bash understands."""
    value = Path(path).resolve().as_posix()
    if len(value) >= 3 and value[1:3] == ":/":
        if Path("C:/Program Files/Git/bin/bash.exe").exists():
            return f"/{value[0].lower()}/{value[3:]}"
        return f"/mnt/{value[0].lower()}/{value[3:]}"
    return value


BASH = find_bash()
RUNTIME_SH_BASH = bash_path(RUNTIME_SH)
OS_SH_BASH = bash_path(OS_SH)


def run_bash(script, env=None, timeout=10):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    r = subprocess.run(
        [BASH, "-c", script],
        capture_output=True, text=True, timeout=timeout, env=merged,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


@unittest.skipUnless(BASH, "bash not available")
@unittest.skipUnless(RUNTIME_SH.exists(), "scripts/runtime.sh not present")
class TestRuntimeGuards(unittest.TestCase):
    def test_os_variable_set(self):
        rc, out, err = run_bash(f'source "{RUNTIME_SH_BASH}"; echo "$OS"')
        self.assertEqual(rc, 0, err)
        self.assertIn(out, ("windows", "macos", "linux"))

    def test_python_available_variable(self):
        rc, out, err = run_bash(f'source "{RUNTIME_SH_BASH}"; echo "$PYTHON_AVAILABLE"')
        self.assertEqual(rc, 0, err)
        self.assertIn(out, ("true", "false"))

    def test_runtime_loaded_guard(self):
        rc, out, _ = run_bash(
            f'source "{RUNTIME_SH_BASH}"; echo "${{_LSTACK_RUNTIME_LOADED:-unset}}"'
        )
        self.assertEqual(rc, 0)

    def test_os_loaded_guard(self):
        rc, out, _ = run_bash(
            f'source "{OS_SH_BASH}"; echo "${{_LSTACK_OS_LOADED:-unset}}"'
        )
        self.assertEqual(rc, 0)


@unittest.skipUnless(BASH, "bash not available")
@unittest.skipUnless(RUNTIME_SH.exists(), "scripts/runtime.sh not present")
class TestRunPython(unittest.TestCase):
    def test_run_python_inline_version(self):
        rc, out, err = run_bash(
            f'source "{RUNTIME_SH_BASH}"; run_python -c "import sys; print(sys.version_info.major)"'
        )
        if out == "" and rc != 0:
            self.skipTest("No Python available in this environment")
        self.assertEqual(out, "3", f"Expected Python 3, got: {out!r} err: {err}")

    def test_run_python_json(self):
        rc, out, err = run_bash(
            f'source "{RUNTIME_SH_BASH}"; run_python -c "import json; print(json.dumps({{\'ok\': True}}))"'
        )
        if rc != 0 or not out:
            self.skipTest("No Python available")
        data = json.loads(out)
        self.assertTrue(data["ok"])

    def test_run_python_unavailable_returns_127(self):
        rc, out, err = run_bash(
            f'LSTACK_FORCE_PYTHON_UNAVAILABLE=1 source "{RUNTIME_SH_BASH}"; '
            f'run_python -c "print(1)"; echo "exit:$?"',
            env={"LSTACK_FORCE_PYTHON_UNAVAILABLE": "1"},
        )
        self.assertIn("exit:127", out)

    def test_py_launcher_not_single_executable(self):
        # "py -3" must NOT be used as a single executable path in run_python.
        # Verify the py-launcher branch calls `py` with `-3` as a separate arg.
        rc, out, err = run_bash(textwrap.dedent(f"""
            source "{RUNTIME_SH_BASH}"
            PYTHON_MODE=py-launcher
            PYTHON_EXE=""
            py() {{ echo "called-py: $*"; }}
            export -f py 2>/dev/null || true
            run_python -c "print(1)" 2>/dev/null || true
            echo done
        """))
        self.assertEqual(rc, 0)
        self.assertIn("done", out)


@unittest.skipUnless(BASH, "bash not available")
@unittest.skipUnless(RUNTIME_SH.exists(), "scripts/runtime.sh not present")
class TestPathHelpers(unittest.TestCase):
    def test_normalize_hook_path_backslash(self):
        rc, out, err = run_bash(
            f'source "{RUNTIME_SH_BASH}"; normalize_hook_path "C:\\\\Users\\\\Name\\\\file"'
        )
        self.assertEqual(rc, 0, err)
        self.assertNotIn("\\", out)

    def test_normalize_hook_path_forward_slash_windows(self):
        rc, out, err = run_bash(
            f'source "{RUNTIME_SH_BASH}"; normalize_hook_path "C:/Users/Name/file"'
        )
        self.assertEqual(rc, 0, err)
        self.assertNotIn("\\", out)

    def test_normalize_preserves_spaces(self):
        tmpdir = tempfile.mkdtemp(prefix="lstack test ")
        try:
            tmpdir_bash = bash_path(tmpdir)
            rc, out, err = run_bash(
                f'source "{RUNTIME_SH_BASH}"; normalize_hook_path "{tmpdir_bash}"'
            )
            self.assertEqual(rc, 0, err)
            self.assertIn(" ", out, "Spaces must be preserved in path")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_normalize_home_expansion(self):
        rc, out, err = run_bash(
            f'source "{RUNTIME_SH_BASH}"; normalize_hook_path "~/.claude"'
        )
        self.assertEqual(rc, 0, err)
        self.assertNotIn("~", out)

    def test_posix_path_passthrough(self):
        rc, out, err = run_bash(
            f'source "{RUNTIME_SH_BASH}"; normalize_hook_path "/home/user/project"'
        )
        self.assertEqual(rc, 0, err)
        self.assertIn("user/project", out)

    def test_drive_d_path(self):
        rc, out, err = run_bash(
            f'source "{RUNTIME_SH_BASH}"; normalize_hook_path "D:\\\\Work Space\\\\file"'
        )
        self.assertEqual(rc, 0, err)
        self.assertNotIn("\\", out)


@unittest.skipUnless(BASH, "bash not available")
@unittest.skipUnless(RUNTIME_SH.exists(), "scripts/runtime.sh not present")
class TestPythonDetectionOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_shim(self, name, body):
        p = self.bin / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
        return p

    def _valid_shim(self):
        exe = shlex.quote(bash_path(sys.executable))
        return f"#!/usr/bin/env sh\nexec {exe} \"$@\"\n"

    def _broken_shim(self):
        return "#!/usr/bin/env sh\nexit 127\n"

    def _run(self, extra_env=""):
        bin_bash = shlex.quote(bash_path(self.bin))
        return subprocess.run(
            [BASH, "-c",
             f'export PATH="{bash_path(self.bin)}:/usr/bin:/bin"; '
             f'export LSTACK_SKIP_ABSOLUTE_PYTHON=1; {extra_env} '
             f'source "{RUNTIME_SH_BASH}"; '
             f'echo "available=$PYTHON_AVAILABLE mode=$PYTHON_MODE"'],
            capture_output=True, text=True,
        )

    def test_python3_provider_detected(self):
        self._write_shim("python3", self._valid_shim())
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("available=true", r.stdout)

    def test_python_fallback_when_python3_broken(self):
        self._write_shim("python3", self._broken_shim())
        self._write_shim("python", self._valid_shim())
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("available=true", r.stdout)

    def test_no_python_sets_available_false(self):
        self._write_shim("python3", self._broken_shim())
        self._write_shim("python", self._broken_shim())
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("available=false", r.stdout)

    def test_detection_rejects_python2(self):
        # A stub that reports version 2 should be rejected
        self._write_shim("python3", "#!/usr/bin/env sh\necho 2\n")
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("available=false", r.stdout)

    def test_py_launcher_mode_detected(self):
        # Simulate Windows: uname returns MINGW, python3/python broken, py works
        self._write_shim("uname", "#!/usr/bin/env sh\nprintf 'MINGW64_NT-10.0\\n'\n")
        self._write_shim("python3", self._broken_shim())
        self._write_shim("python", self._broken_shim())
        exe = shlex.quote(bash_path(sys.executable))
        self._write_shim("py",
            f'#!/usr/bin/env sh\nif [ "$1" = "-3" ]; then shift; exec {exe} "$@"; fi\nexit 127\n')
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("available=true", r.stdout)
        self.assertIn("py-launcher", r.stdout)


if __name__ == "__main__":
    unittest.main()
