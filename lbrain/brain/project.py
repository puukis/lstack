"""Project identity helpers for LBrain."""

import hashlib
import os
import subprocess
from pathlib import Path

from .platform import normalize_path, path_identity, platform_facts


def sha256_text(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def git_value(args, cwd):
    try:
        return subprocess.check_output(
            ["git"] + args,
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip() or None
    except Exception:
        return None


def find_project_root(cwd=None):
    cwd_path = Path(cwd or os.getcwd()).resolve()
    git_root = git_value(["rev-parse", "--show-toplevel"], cwd_path)
    if git_root:
        return Path(git_root).resolve()
    return cwd_path


def project_info(cwd=None):
    root = find_project_root(cwd)
    display = normalize_path(str(root))
    identity = path_identity(display)
    remote = git_value(["remote", "get-url", "origin"], root)
    branch = git_value(["branch", "--show-current"], root)
    facts = platform_facts()
    repo_id = sha256_text(remote) if remote else None
    return {
        "root": root,
        "root_path_display": display,
        "root_path_hash": sha256_text(identity),
        "repo_id": repo_id,
        "git_remote_hash": sha256_text(remote) if remote else None,
        "git_branch": branch,
        "name": root.name,
        "platform": facts["os"],
        "shell_mode": facts["shell_mode"],
    }


def lstack_project_signals(project_or_root):
    root = project_or_root.get("root") if isinstance(project_or_root, dict) else project_or_root
    if not root and isinstance(project_or_root, dict):
        root = project_or_root.get("root_path_display")
    root = Path(root or ".").resolve()
    signals = []
    if (root / "bin" / "lstack").is_file():
        signals.append("bin/lstack")
    if (root / "lbrain" / "brain.py").is_file():
        signals.append("lbrain/brain.py")
    if (root / "docs" / "lbrain.md").is_file():
        signals.append("docs/lbrain.md")
    install_sh = root / "install.sh"
    if install_sh.is_file():
        try:
            text = install_sh.read_text(encoding="utf-8", errors="ignore")
            if "lstack" in text and "CLAUDE_DIR" in text:
                signals.append("install.sh")
        except Exception:
            pass
    readme = root / "README.md"
    if readme.is_file():
        try:
            head = readme.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
            if "lstack" in head and ("claude code" in head or "local trust brain" in head):
                signals.append("README.md")
        except Exception:
            pass
    return signals


def is_lstack_project(project_or_root):
    return len(lstack_project_signals(project_or_root)) >= 2
