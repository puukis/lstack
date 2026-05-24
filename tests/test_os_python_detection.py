import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OS_SH = ROOT / "scripts" / "os.sh"


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


class PythonDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self.tmp.name) / "bin"
        self.home = Path(self.tmp.name) / "home"
        self.claude = self.home / ".claude"
        (self.claude / "scripts").mkdir(parents=True)
        self.bin.mkdir()
        shutil.copy2(OS_SH, self.claude / "scripts" / "os.sh")
        self.bash = find_bash()

    def tearDown(self):
        self.tmp.cleanup()

    def write_exe(self, name, body):
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
        return path

    def valid_python_shim(self):
        exe = shlex.quote(bash_path(sys.executable))
        return f"""#!/usr/bin/env sh
exec {exe} "$@"
"""

    def broken_shim(self):
        return "#!/usr/bin/env sh\nexit 127\n"

    def run_probe(self, path):
        home = shlex.quote(bash_path(self.home))
        probe_path = shlex.quote(f"{bash_path(self.bin)}:/usr/bin:/bin")
        proc = subprocess.run(
            [
                self.bash,
                "-c",
                f"export HOME={home}; export PATH={probe_path}; export LSTACK_SKIP_ABSOLUTE_PYTHON=1; " + textwrap.dedent(
                    """
                    source "$HOME/.claude/scripts/os.sh"
                    printf 'available=%s\n' "$PYTHON_AVAILABLE"
                    printf 'mode=%s\n' "$PYTHON_MODE"
                    printf 'exe=%s\n' "$PYTHON_EXE"
                    run_python -c 'print("ok")'
                    """
                ),
            ],
            text=True,
            capture_output=True,
        )
        return proc

    @unittest.skipUnless(find_bash(), "bash is required")
    def test_detects_python3(self):
        self.write_exe("python3", self.valid_python_shim())
        proc = self.run_probe(os.environ["PATH"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("available=true", proc.stdout)
        self.assertIn("mode=exe", proc.stdout)
        self.assertTrue(proc.stdout.rstrip().endswith("ok"))

    @unittest.skipUnless(find_bash(), "bash is required")
    def test_detects_python_after_broken_python3(self):
        self.write_exe("python3", self.broken_shim())
        self.write_exe("python", self.valid_python_shim())
        proc = self.run_probe(os.environ["PATH"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("available=true", proc.stdout)
        self.assertIn("mode=exe", proc.stdout)

    @unittest.skipUnless(find_bash(), "bash is required")
    def test_detects_windows_py_launcher_mode(self):
        self.write_exe("uname", "#!/usr/bin/env sh\nprintf 'MINGW64_NT-10.0\\n'\n")
        self.write_exe("python3", self.broken_shim())
        self.write_exe("python", self.broken_shim())
        self.write_exe(
            "py",
            (
                "#!/usr/bin/env sh\n"
                f"if [ \"$1\" = \"-3\" ]; then shift; exec {shlex.quote(bash_path(sys.executable))} \"$@\"; fi\n"
                "exit 127\n"
            ),
        )
        proc = self.run_probe(os.environ["PATH"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("available=true", proc.stdout)
        self.assertIn("mode=py-launcher", proc.stdout)
        self.assertIn("ok", proc.stdout)

    @unittest.skipUnless(find_bash(), "bash is required")
    def test_no_python_does_not_crash(self):
        self.write_exe("python3", self.broken_shim())
        self.write_exe("python", self.broken_shim())
        home = shlex.quote(bash_path(self.home))
        path = shlex.quote(bash_path(self.bin))
        proc = subprocess.run(
            [
                self.bash,
                "-c",
                f'export HOME={home}; export PATH={path}; export LSTACK_FORCE_PYTHON_UNAVAILABLE=1; source "$HOME/.claude/scripts/os.sh"; printf "%s\\n" "$PYTHON_AVAILABLE"; run_python -c "print(1)" || true',
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("false", proc.stdout)


if __name__ == "__main__":
    unittest.main()
