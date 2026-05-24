"""Tests for scripts/lbrain-capture-hook.py - hook wrapper script."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = ROOT / "scripts" / "lbrain-capture-hook.py"

sys.path.insert(0, str(ROOT / "lbrain"))


def _run_hook(payload_dict, env_extra=None, cwd=None):
    """Run lbrain-capture-hook.py post-tool with a JSON payload on stdin."""
    env = os.environ.copy()
    env["LSTACK_BRAIN_AUTO_LEARN"] = "1"
    env["LSTACK_BRAIN_AUTO_PROMOTE"] = "1"
    if env_extra:
        env.update(env_extra)

    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT), "post-tool"],
        input=json.dumps(payload_dict),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd or tempfile.gettempdir(),
        timeout=30,
    )
    return proc


def _make_bash_payload(command, exit_code=0, output=""):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"exit_code": exit_code, "output": output},
    }


class TestHookWrapperBasic(unittest.TestCase):
    def test_script_exists(self):
        self.assertTrue(HOOK_SCRIPT.exists(), f"Hook script not found: {HOOK_SCRIPT}")

    def test_hook_exits_zero_on_empty_stdin(self):
        env = os.environ.copy()
        proc = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT), "post-tool"],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0)

    def test_hook_exits_zero_on_malformed_json(self):
        env = os.environ.copy()
        proc = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT), "post-tool"],
            input="{not valid json",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0)

    def test_hook_exits_zero_on_valid_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            proc = _run_hook(
                _make_bash_payload("ls", exit_code=0, output="file.txt"),
                env_extra={"LSTACK_DB_PATH": str(db_path)},
                cwd=tmp,
            )
        self.assertEqual(proc.returncode, 0)

    def test_hook_exits_zero_when_autolearn_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            proc = _run_hook(
                _make_bash_payload("python3 missing.py", exit_code=127, output="not found"),
                env_extra={"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "0"},
                cwd=tmp,
            )
        self.assertEqual(proc.returncode, 0)

    def test_hook_produces_no_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            proc = _run_hook(
                _make_bash_payload("ls", exit_code=0),
                env_extra={"LSTACK_DB_PATH": str(db_path)},
                cwd=tmp,
            )
        self.assertEqual(proc.stdout, "")


class TestHookEventRecording(unittest.TestCase):
    def test_bash_failure_records_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            proc = _run_hook(
                _make_bash_payload("python3 missing.py", exit_code=127, output="python3: command not found"),
                env_extra={"LSTACK_DB_PATH": str(db_path)},
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 0)

            from brain.db import connect, ensure_project
            from brain.capture import list_events
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"])
            con.close()
        self.assertGreater(len(events), 0)

    def test_repeated_bash_failure_auto_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            payload = _make_bash_payload("python3 missing.py", exit_code=127, output="command not found")
            for _ in range(3):
                proc = _run_hook(
                    payload,
                    env_extra={"LSTACK_DB_PATH": str(db_path)},
                    cwd=tmp,
                )
                self.assertEqual(proc.returncode, 0)

            from brain.db import connect, ensure_project
            from brain.attempts import list_attempts
            con = connect(db_path)
            project = ensure_project(con, tmp)
            attempts = list_attempts(con, project["id"])
            con.close()
        self.assertGreater(len(attempts), 0)

    def test_package_manager_hook_records_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            pkg = {"name": "test", "packageManager": "pnpm@10.0.0"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "pnpm-lock.yaml").touch()
            proc = _run_hook(
                _make_bash_payload("pnpm test", exit_code=0, output="tests passed"),
                env_extra={"LSTACK_DB_PATH": str(db_path)},
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 0)

            from brain.db import connect, ensure_project
            from brain.capture import list_events
            from brain.decisions import get_decision
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"], event_type="package_manager_detection")
            decision = get_decision(con, project["id"], "package-manager-pnpm")
            con.close()
        self.assertGreater(len(events), 0)
        self.assertIsNotNone(decision)

    def test_redaction_blocks_promotion_via_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            payload = _make_bash_payload(
                'curl -H "Authorization: Bearer sk-secret-xyz999" https://api.example.com',
                exit_code=1,
                output="failed with token sk-secret-xyz999",
            )
            for _ in range(3):
                _run_hook(payload, env_extra={"LSTACK_DB_PATH": str(db_path)}, cwd=tmp)

            from brain.db import connect, ensure_project
            from brain.capture import list_candidates
            from brain.attempts import list_attempts
            con = connect(db_path)
            project = ensure_project(con, tmp)
            attempts = list_attempts(con, project["id"])
            candidates = list_candidates(con, project["id"], status=None)
            con.close()

        # Any suspect/blocked candidate must not be promoted
        for c in candidates:
            if c.get("redaction_status") in ("suspect", "blocked"):
                self.assertNotEqual(c["status"], "promoted")
        # No attempt should be created from a redacted command
        for a in attempts:
            self.assertNotIn("sk-secret-xyz999", str(a.get("command_redacted") or ""))


class TestHookSelfCheck(unittest.TestCase):
    def test_self_check_outputs_json(self):
        env = os.environ.copy()
        proc = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT), "self-check"],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0)
        output = proc.stdout.strip()
        if output:
            data = json.loads(output)
            self.assertIn("auto_learn_enabled", data)

    def test_doctor_alias_outputs_json(self):
        env = os.environ.copy()
        proc = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT), "doctor"],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0)


class TestHookNoClaude(unittest.TestCase):
    def test_no_claude_p_in_hook_scripts(self):
        """Lifecycle hooks must never call claude -p recursively."""
        import re
        hooks_dir = ROOT / "hooks"
        capture_hook = ROOT / "scripts" / "lbrain-capture-hook.py"
        pattern = re.compile(r"\bclaude\s+-p\b")
        violations = []
        paths_to_check = list(hooks_dir.glob("*.sh")) + list(hooks_dir.glob("*.py"))
        if capture_hook.exists():
            paths_to_check.append(capture_hook)
        for path in paths_to_check:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                in_string = False
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    # Skip comment lines and docstring lines
                    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                        continue
                    if pattern.search(line):
                        violations.append(f"{path.name}:{i}: {stripped}")
            except Exception:
                pass
        self.assertEqual(violations, [], "Found active claude -p calls in hooks:\n" + "\n".join(violations))


class TestGenSettings(unittest.TestCase):
    def test_gen_settings_includes_bash_in_posttooluse(self):
        """gen-settings.sh must output a PostToolUse matcher that includes Bash."""
        gen_settings_path = ROOT / "scripts" / "gen-settings.sh"
        self.assertTrue(gen_settings_path.exists())
        content = gen_settings_path.read_text(encoding="utf-8")
        # The matcher string must include Bash
        self.assertIn("Bash|Write|Edit|MultiEdit", content)

    def test_gen_settings_python_output_includes_bash(self):
        """The Python block in gen-settings.sh must have Bash in the matcher."""
        gen_settings_path = ROOT / "scripts" / "gen-settings.sh"
        content = gen_settings_path.read_text(encoding="utf-8")
        # Find the PostToolUse line in the Python block
        lines = content.splitlines()
        posttooluse_lines = [l for l in lines if "PostToolUse" in l and "matcher" in l]
        self.assertTrue(len(posttooluse_lines) > 0, "No PostToolUse matcher line found")
        for line in posttooluse_lines:
            self.assertIn("Bash", line, f"PostToolUse matcher does not include Bash: {line}")


def _bash_n(script_path):
    """Run bash -n on a shell script. Returns (returncode, stderr).

    Passes content via stdin to avoid Windows path resolution issues.
    """
    import subprocess
    import shutil

    bash_candidates = [
        "bash",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    bash_exe = None
    for candidate in bash_candidates:
        found = shutil.which(candidate)
        if found:
            bash_exe = found
            break
        if os.path.isfile(candidate):
            bash_exe = candidate
            break

    if bash_exe is None:
        return None, "bash not found"

    import tempfile
    import shutil as _shutil

    try:
        content = Path(script_path).read_bytes()
    except Exception as exc:
        return None, f"could not read script: {exc}"

    # Write to a temp file then check via bash -n with MSYS2 path
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tf:
        tf.write(content)
        tmp_path = tf.name

    try:
        # Convert Windows temp path to MSYS2 style for Git Bash
        import re
        tmp_msys = tmp_path
        m = re.match(r"^([A-Za-z]):\\(.+)$", tmp_path.replace("/", "\\"))
        if m:
            tmp_msys = "/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/")

        result = subprocess.run(
            [bash_exe, "-n", tmp_msys],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        return result.returncode, result.stderr
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


class TestHookShSyntax(unittest.TestCase):
    def test_post_tool_sh_bash_syntax(self):
        """hooks/post-tool.sh must pass bash -n syntax check."""
        rc, stderr = _bash_n(ROOT / "hooks" / "post-tool.sh")
        if rc is None:
            self.skipTest("bash not available")
        self.assertEqual(rc, 0, f"bash -n failed:\n{stderr}")

    def test_stop_sh_bash_syntax(self):
        """hooks/stop.sh must pass bash -n."""
        rc, stderr = _bash_n(ROOT / "hooks" / "stop.sh")
        if rc is None:
            self.skipTest("bash not available")
        self.assertEqual(rc, 0, f"bash -n failed:\n{stderr}")


class TestPathNormalization(unittest.TestCase):
    def test_windows_path_does_not_double_drive_letter(self):
        """Windows Git Bash path normalization must not create C:/c/Users."""
        from brain.platform import normalize_path
        # Git Bash style /c/Users/test
        result = normalize_path("/c/Users/test")
        self.assertNotIn("/c/c/", result)
        self.assertNotIn("C:/c/", result)


if __name__ == "__main__":
    unittest.main()
