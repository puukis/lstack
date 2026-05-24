import contextlib
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SAFETY_PY = ROOT / "scripts" / "safety.py"
PRE_TOOL = ROOT / "hooks" / "pre-tool.sh"
LSTACK = ROOT / "bin" / "lstack"


def bash_path(path):
    value = Path(path).resolve().as_posix()
    match = re.match(r"^([A-Za-z]):/(.*)$", value)
    if match:
        if Path("C:/Program Files/Git/bin/bash.exe").exists():
            return f"/{match.group(1).lower()}/{match.group(2)}"
        return f"/mnt/{match.group(1).lower()}/{match.group(2)}"
    return value


def find_bash():
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return shutil.which("bash")


def load_safety():
    spec = importlib.util.spec_from_file_location("lstack_safety_test", SAFETY_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SafetyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.project = Path(self.tmp.name) / "project"
        self.logs = self.home / ".claude" / "logs"
        self.home.mkdir()
        self.project.mkdir()
        (self.project / ".git").mkdir()
        self.env = {
            "HOME": self.home.as_posix(),
            "CLAUDE_SESSION_ID": "test-session",
            "LSTACK_LOG_DIR": self.logs.as_posix(),
            "LSTACK_STATE_TTL_SECONDS": "999999",
        }
        self.safety = load_safety()
        self.old_cwd = os.getcwd()
        os.chdir(self.project)
        self.env_patch = mock.patch.dict(os.environ, self.env, clear=False)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def set_freeze(self, paths):
        allowed = self.safety.resolve_allowed_paths(paths)
        self.safety.write_json_state(
            "freeze",
            {
                "active": True,
                "created_at": self.safety.iso_now(),
                "session_id": "test-session",
                "mode": "freeze",
                "allowed_paths": allowed,
                "original_args": paths,
            },
        )
        return allowed

    def set_safety(self, mode):
        self.safety.write_json_state(
            "safety",
            {
                "active": mode != "off",
                "mode": mode,
                "created_at": self.safety.iso_now(),
                "session_id": "test-session",
                "allow_once": [],
            },
        )

    def hook_payload(self, tool, tool_input):
        return json.dumps({"tool_name": tool, "tool_input": tool_input})


class FreezeTests(SafetyTestCase):
    def test_no_state_allows_edit(self):
        result = self.safety.handle_hook(
            self.hook_payload("Write", {"file_path": "src/a.py"})
        )
        self.assertIsNone(result)

    def test_active_freeze_allows_file_inside_allowed_dir(self):
        self.set_freeze(["src"])
        result = self.safety.handle_hook(
            self.hook_payload("Edit", {"file_path": "src/a.py"})
        )
        self.assertIsNone(result)

    def test_active_freeze_denies_file_outside_allowed_dir(self):
        self.set_freeze(["src"])
        result = self.safety.handle_hook(
            self.hook_payload("Write", {"file_path": "tests/a.py"})
        )
        self.assertIn('"permissionDecision":"deny"', result)
        self.assertIn("Blocked edit outside boundary", result)

    def test_src_does_not_allow_src_old(self):
        self.set_freeze(["src"])
        result = self.safety.handle_hook(
            self.hook_payload("Write", {"file_path": "src-old/a.py"})
        )
        self.assertIn('"permissionDecision":"deny"', result)

    def test_multiple_allowed_dirs(self):
        self.set_freeze(["src/auth", "tests/auth"])
        self.assertIsNone(
            self.safety.handle_hook(
                self.hook_payload("MultiEdit", {"file_path": "tests/auth/test_login.py"})
            )
        )
        result = self.safety.handle_hook(
            self.hook_payload("MultiEdit", {"file_path": "tests/billing/test_plan.py"})
        )
        self.assertIn('"permissionDecision":"deny"', result)

    def test_relative_path_and_non_existing_file_inside_allowed_dir(self):
        self.set_freeze(["src/auth"])
        result = self.safety.handle_hook(
            self.hook_payload("Write", {"file_path": "src/auth/new_file.py"})
        )
        self.assertIsNone(result)

    def test_malformed_freeze_state_blocks_edit(self):
        path = self.safety.state_file("freeze")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        result = self.safety.handle_hook(
            self.hook_payload("Edit", {"file_path": "src/a.py"})
        )
        self.assertIn('"permissionDecision":"deny"', result)
        self.assertIn("state file is malformed", result)

    def test_unfreeze_clears_state(self):
        self.set_freeze(["src"])
        self.assertTrue(self.safety.clear_state("freeze"))
        result = self.safety.handle_hook(
            self.hook_payload("Write", {"file_path": "other/a.py"})
        )
        self.assertIsNone(result)

    def test_windows_git_bash_path_normalization(self):
        git_bash = self.safety.normalize_path("/c/Users/Example/repo/src")
        windows = self.safety.normalize_path("C:/Users/Example/repo/src")
        self.assertEqual(git_bash.key, windows.key)


class CarefulTests(SafetyTestCase):
    def test_rm_rf_dangerous_path_asks_in_careful(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "rm -rf src"})
        self.assertIn('"permissionDecision":"ask"', result)
        self.assertIn("rm-recursive", result)

    def test_rm_rf_dangerous_path_denies_in_strict(self):
        self.set_safety("strict")
        result = self.safety.bash_hook_decision({"command": "rm -rf src"})
        self.assertIn('"permissionDecision":"deny"', result)
        self.assertIn("rm-recursive", result)

    def test_rm_rf_node_modules_allowed_if_repo_local(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "rm -rf node_modules"})
        self.assertIsNone(result)

    def test_rm_rf_root_is_never_safe_exception(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "rm -rf /"})
        self.assertIn('"permissionDecision":"deny"', result)
        self.assertIn("rm-recursive-critical", result)

    def test_git_push_force_detected(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "git push --force origin main"})
        self.assertIn('"permissionDecision":"deny"', result)
        self.assertIn("git-force-push", result)

    def test_git_force_with_lease_not_confused_with_force(self):
        self.set_safety("strict")
        result = self.safety.bash_hook_decision(
            {"command": "git push --force-with-lease origin main"}
        )
        self.assertIsNone(result)

    def test_git_reset_hard_detected(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "git reset --hard HEAD"})
        self.assertIn('"permissionDecision":"ask"', result)
        self.assertIn("git-reset-hard", result)

    def test_docker_system_prune_detected(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "docker system prune -a"})
        self.assertIn('"permissionDecision":"ask"', result)
        self.assertIn("docker-system-prune", result)

    def test_kubectl_delete_detected(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "kubectl delete pod app"})
        self.assertIn('"permissionDecision":"ask"', result)
        self.assertIn("kubectl-delete", result)

    def test_drop_table_detected(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision(
            {"command": "psql -c 'DROP TABLE users;'"}
        )
        self.assertIn('"permissionDecision":"deny"', result)
        self.assertIn("drop-table", result)

    def test_chmod_recursive_777_detected(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "chmod -R 777 uploads"})
        self.assertIn('"permissionDecision":"ask"', result)
        self.assertIn("chmod-recursive-777", result)

    def test_harmless_command_allowed(self):
        self.set_safety("strict")
        result = self.safety.bash_hook_decision({"command": "python -m unittest"})
        self.assertIsNone(result)

    def test_pnpm_store_prune_allowed(self):
        self.set_safety("strict")
        result = self.safety.bash_hook_decision({"command": "pnpm store prune"})
        self.assertIsNone(result)

    def test_rust_target_allowed_when_repo_local(self):
        (self.project / "Cargo.toml").write_text("[package]\nname = \"x\"\n", encoding="utf-8")
        self.set_safety("strict")
        result = self.safety.bash_hook_decision({"command": "rm -rf target"})
        self.assertIsNone(result)

    def test_npm_cache_clean_force_warns(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision({"command": "npm cache clean --force"})
        self.assertIn('"permissionDecision":"ask"', result)
        self.assertIn("npm-cache-clean-force", result)

    def test_inline_confirm_override_allows_opt_in_risk(self):
        self.set_safety("strict")
        result = self.safety.bash_hook_decision(
            {"command": "LSTACK_CONFIRM_DESTRUCTIVE=1 rm -rf src"}
        )
        self.assertIsNone(result)

    def test_inline_confirm_does_not_override_global_hard_block(self):
        self.set_safety("careful")
        result = self.safety.bash_hook_decision(
            {"command": "LSTACK_CONFIRM_DESTRUCTIVE=1 rm -rf /"}
        )
        self.assertIn('"permissionDecision":"deny"', result)
        self.assertIn("rm-recursive-critical", result)


class GuardTests(SafetyTestCase):
    def test_guard_activates_safety_and_freeze(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.safety.main(["guard", "src"])
        status = self.safety.status_data()
        self.assertEqual(status["safety_mode"], "careful")
        self.assertTrue(status["freeze_active"])
        self.assertEqual(len(status["freeze_allowed_paths"]), 1)

    def test_guard_blocks_edit_outside_path(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.safety.main(["guard", "src"])
        result = self.safety.handle_hook(
            self.hook_payload("Write", {"file_path": "outside/a.py"})
        )
        self.assertIn('"permissionDecision":"deny"', result)

    def test_guard_warns_dangerous_bash_command(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.safety.main(["guard", "src"])
        result = self.safety.handle_hook(
            self.hook_payload("Bash", {"command": "rm -rf src"})
        )
        self.assertIn('"permissionDecision":"ask"', result)

    def test_guard_clear_removes_freeze_and_safety(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.safety.main(["guard", "src"])
            self.safety.main(["guard", "--clear"])
        status = self.safety.status_data()
        self.assertEqual(status["safety_mode"], "off")
        self.assertFalse(status["freeze_active"])


class CliTests(SafetyTestCase):
    def make_cli_home(self):
        claude = self.home / ".claude"
        (claude / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / "os.sh", claude / "scripts" / "os.sh")
        shutil.copy2(ROOT / "scripts" / "safety.py", claude / "scripts" / "safety.py")
        return claude

    def run_lstack(self, *args):
        self.make_cli_home()
        env = os.environ.copy()
        env.update(self.env)
        command = " ".join(
            [
                f"HOME={shlex.quote(bash_path(self.home))}",
                f"LSTACK_LOG_DIR={shlex.quote(bash_path(self.logs))}",
                "CLAUDE_SESSION_ID=test-session",
                "LSTACK_STATE_TTL_SECONDS=999999",
                "bash",
                shlex.quote(bash_path(LSTACK)),
                *[shlex.quote(arg) for arg in args],
            ]
        )
        result = subprocess.run(
            [find_bash(), "-c", command],
            cwd=self.project,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout

    @unittest.skipUnless(find_bash(), "bash is required for CLI smoke tests")
    def test_lstack_safety_status_and_freeze_unfreeze(self):
        self.run_lstack("safety", "careful")
        status = self.run_lstack("safety", "status")
        self.assertIn("safety mode: careful", status)
        freeze = self.run_lstack("freeze", "src")
        self.assertIn("Freeze active", freeze)
        status = self.run_lstack("safety", "status")
        self.assertIn("freeze active: true", status)
        unfreeze = self.run_lstack("unfreeze")
        self.assertIn("Freeze cleared", unfreeze)


class HookSmokeTests(SafetyTestCase):
    def make_hook_home(self):
        claude = self.home / ".claude"
        (claude / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / "os.sh", claude / "scripts" / "os.sh")
        shutil.copy2(ROOT / "scripts" / "safety.py", claude / "scripts" / "safety.py")
        return claude

    def run_hook(self, payload):
        self.make_hook_home()
        env = os.environ.copy()
        env.update(self.env)
        command = " ".join(
            [
                f"HOME={shlex.quote(bash_path(self.home))}",
                f"LSTACK_LOG_DIR={shlex.quote(bash_path(self.logs))}",
                "CLAUDE_SESSION_ID=test-session",
                "LSTACK_STATE_TTL_SECONDS=999999",
                "bash",
                shlex.quote(bash_path(PRE_TOOL)),
            ]
        )
        return subprocess.run(
            [find_bash(), "-c", command],
            input=json.dumps(payload),
            cwd=self.project,
            env=env,
            text=True,
            capture_output=True,
        )

    @unittest.skipUnless(find_bash(), "bash is required for hook smoke tests")
    def test_hook_allows_harmless_bash_silently(self):
        proc = self.run_hook({"tool_name": "Bash", "tool_input": {"command": "echo ok"}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    @unittest.skipUnless(find_bash(), "bash is required for hook smoke tests")
    def test_hook_denies_write_outside_freeze_with_json(self):
        self.set_freeze(["src"])
        proc = self.run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": "outside/a.py"}}
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"permissionDecision":"deny"', proc.stdout)
        self.assertIn("Freeze active", proc.stdout)

    @unittest.skipUnless(find_bash(), "bash is required for hook smoke tests")
    def test_hook_allows_multiedit_inside_freeze_silently(self):
        self.set_freeze(["src"])
        proc = self.run_hook(
            {"tool_name": "MultiEdit", "tool_input": {"file_path": "src/a.py"}}
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    @unittest.skipUnless(find_bash(), "bash is required for hook smoke tests")
    def test_hook_asks_for_careful_risky_bash(self):
        self.set_safety("careful")
        proc = self.run_hook({"tool_name": "Bash", "tool_input": {"command": "rm -rf src"}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"permissionDecision":"ask"', proc.stdout)
        self.assertIn("rm-recursive", proc.stdout)

    @unittest.skipUnless(find_bash(), "bash is required for hook smoke tests")
    def test_hook_denies_global_hard_block_with_json(self):
        proc = self.run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "psql -c 'DROP TABLE users;'"}}
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"permissionDecision":"deny"', proc.stdout)
        self.assertIn("drop-table", proc.stdout)


if __name__ == "__main__":
    unittest.main()
