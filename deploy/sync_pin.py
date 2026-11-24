"""Synchronize only the active pycomcigan requirements line."""
import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from deploy.fork_manifest import HEX40

PIN = re.compile(r"^pycomcigan @ git\+https://github\.com/Transient-Onlooker/pycomcigan\.git@[0-9a-f]{40}(?=\r?$)", re.MULTILINE)


def replace_pin(content, sha):
    if not HEX40.fullmatch(sha) or len(PIN.findall(content)) != 1:
        raise ValueError("Requirements pin is invalid or ambiguous")
    return PIN.sub("pycomcigan @ git+https://github.com/Transient-Onlooker/pycomcigan.git@" + sha, content)


def sync(sha, key, attempts=3):
    if not HEX40.fullmatch(sha):
        raise ValueError("Invalid component SHA")
    key = Path(key)
    if not key.is_file() or key.is_symlink() or key.stat().st_mode & 0o077:
        raise ValueError("Pin synchronization key missing or has unsafe permissions")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -i " + shlex.quote(str(key))
    last_error = None
    for attempt in range(attempts):
        try:
            with tempfile.TemporaryDirectory(prefix="opencigan-pin-") as temporary:
                root = Path(temporary) / "repo"
                subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", "main",
                                "git@github.com:Transient-Onlooker/opencigan.git", str(root)], check=True, env=env, timeout=90)
                requirements = root / "backend/requirements.txt"
                original = requirements.read_bytes().decode("utf-8")
                updated = replace_pin(original, sha)
                if updated == original:
                    return "already_synced"
                requirements.write_bytes(updated.encode("utf-8"))
                changed = subprocess.check_output(["git", "-C", str(root), "diff", "--name-only"], env=env, text=True).splitlines()
                if changed != ["backend/requirements.txt"]:
                    raise ValueError("Unexpected source changes")
                subprocess.run(["git", "-C", str(root), "add", "--", "backend/requirements.txt"], check=True, env=env)
                subprocess.run(["git", "-C", str(root), "-c", "user.name=OpenCigan dependency bot",
                                "-c", "user.email=opencigan-dependency-bot@users.noreply.github.com",
                                "-c", "core.hooksPath=/dev/null", "commit", "-m", "Update pycomcigan active commit"],
                               check=True, env=env, timeout=30, stdout=subprocess.DEVNULL)
                subprocess.run(["git", "-C", str(root), "push", "origin", "HEAD:refs/heads/main"], check=True, env=env, timeout=90)
                return "synced"
        except (OSError, subprocess.SubprocessError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError("Pin synchronization failed after retries") from last_error
