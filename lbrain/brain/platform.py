"""Cross-platform path and shell detection for LBrain."""

import os
import platform as platform_lib
import re
from pathlib import Path


def normalize_path(value):
    raw = str(value or "").strip()
    raw = raw.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", raw)
    if m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    m = re.match(r"^/([A-Za-z])/(.*)$", raw)
    if m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    return raw


def path_identity(value):
    normalized = normalize_path(value)
    if re.match(r"^[A-Za-z]:/", normalized):
        return normalized.lower()
    return normalized


def path_warnings(value, shell_mode=None):
    warnings = []
    normalized = str(value or "").replace("\\", "/")
    if (shell_mode or detect_shell_mode()) == "git-bash" and normalized.startswith("/mnt/"):
        warnings.append("WSL /mnt paths are not valid for Windows Git Bash. Use /c/... or /d/... paths.")
    return warnings


def detect_wsl(env=None, proc_version=None):
    env = env if env is not None else os.environ
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    if proc_version is None:
        try:
            proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
        except Exception:
            proc_version = ""
    return "microsoft" in proc_version.lower() or "wsl" in proc_version.lower()


def detect_os(env=None, system_name=None, proc_version=None):
    env = env if env is not None else os.environ
    name = (system_name or platform_lib.system()).lower()
    if name.startswith("darwin"):
        return "macos"
    if name.startswith("linux") and detect_wsl(env=env, proc_version=proc_version):
        return "linux"
    if name.startswith("windows") or env.get("MSYSTEM"):
        return "windows"
    if name.startswith("linux"):
        return "linux"
    return name or "unknown"


def detect_shell_mode(env=None, os_name=None, proc_version=None):
    env = env if env is not None else os.environ
    if (os_name or detect_os(env=env, proc_version=proc_version)) == "linux" and detect_wsl(env=env, proc_version=proc_version):
        return "wsl"
    if env.get("MSYSTEM") or env.get("MINGW_PREFIX"):
        return "git-bash"
    shell = env.get("SHELL", "")
    if "bash" in shell:
        return "bash"
    if os.name == "nt":
        return "windows"
    return Path(shell).name or "unknown"


def path_style_recommendation(os_name=None, shell_mode=None):
    os_name = os_name or detect_os()
    shell_mode = shell_mode or detect_shell_mode()
    if os_name == "windows" and shell_mode == "git-bash":
        return "Use Git Bash with /c/... or /d/... paths. Do not use /mnt/c/... WSL paths."
    if shell_mode == "wsl":
        return "Running in WSL. Windows-specific lstack behavior targets Git Bash; WSL uses normal Linux paths."
    if os_name == "windows":
        return "Use Windows paths or Git Bash MSYS2 paths consistently."
    return "Use native POSIX paths."


def platform_facts(env=None, system_name=None, proc_version=None):
    os_name = detect_os(env=env, system_name=system_name, proc_version=proc_version)
    shell_mode = detect_shell_mode(env=env, os_name=os_name, proc_version=proc_version)
    is_wsl = os_name == "linux" and shell_mode == "wsl"
    warnings = []
    if is_wsl:
        warnings.append("WSL detected. Windows-specific lstack behavior targets Git Bash, not WSL.")
    return {
        "os": os_name,
        "shell_mode": shell_mode,
        "is_wsl": is_wsl,
        "path_style": path_style_recommendation(os_name, shell_mode),
        "warnings": warnings,
    }
