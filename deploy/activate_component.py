"""Atomically switch a verified component, or restore both services."""
import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from deploy.fork_manifest import HEX40, load_release, verify_candidate
from deploy.sync_pin import sync


def systemctl(*args):
    subprocess.run(["systemctl", "--user", *args], check=True)


def write_atomic(path, content):
    temporary = path.with_name("." + path.name + ".tmp-" + str(os.getpid()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def probe(port, path, params, token=None):
    url = "http://127.0.0.1:" + str(port) + path + "?" + urlencode(params)
    headers = {"Authorization": "Bearer " + token} if token else {}
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        result = json.load(response)
    if result.get("schoolId") != params["school"] or not isinstance(result.get("records"), list) or result.get("stale"):
        raise ValueError("Invalid timetable response")
    if token and not all("originalSubject" in row and "originalTeacher" in row for row in result["records"]):
        raise ValueError("Missing original timetable fields")


def wait_ready(port, path, expected):
    for attempt in range(20):
        try:
            with urlopen("http://127.0.0.1:" + str(port) + path, timeout=5) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        except URLError:
            if attempt == 19:
                raise
            time.sleep(0.5)
            continue
        if status != expected:
            raise ValueError("Unexpected readiness response")
        return


def installed_sha(root, home):
    current = root / "current"
    if current.is_symlink():
        target = Path(os.readlink(current))
        if target.parent != root or not HEX40.fullmatch(target.name):
            raise ValueError("Unexpected active component target")
        return target.name
    python = home / "opensigan-releases/current/.venv/bin/python"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    direct_url = subprocess.check_output(
        [str(python), "-c", "import importlib.metadata as m; print(m.distribution('pycomcigan').read_text('direct_url.json'))"],
        text=True, env=environment, timeout=10)
    metadata = json.loads(direct_url)
    sha = metadata.get("vcs_info", {}).get("commit_id")
    if metadata.get("url") != "https://github.com/Transient-Onlooker/pycomcigan.git" or not isinstance(sha, str) or not HEX40.fullmatch(sha):
        raise ValueError("Existing component provenance is unknown")
    return sha


def activate(tag, sha, root, school, week):
    import fcntl

    if not HEX40.fullmatch(sha):
        raise ValueError("Invalid component SHA")
    root = Path(root).resolve(strict=True)
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(root)):
        raise ValueError("Unsupported component root path")
    lock_path = root / ".deploy.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe lock path")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status_file = root / "deployment-status.json"
        if status_file.is_symlink():
            raise ValueError("Unsafe state path")
        try:
            active = installed_sha(root, Path.home())
        except Exception:
            active = None
        state = {"requestedSha": sha, "activeSha": active, "success": False, "verification": {},
                 "rollback": False, "pinSync": "not_started", "phase": "validating",
                 "timestamp": datetime.now(timezone.utc).isoformat()}
        write_atomic(status_file, json.dumps(state) + "\n")
        try:
            return _activate(tag, sha, root, school, week)
        except Exception as error:
            saved = json.loads(status_file.read_text(encoding="utf-8"))
            if saved.get("phase") == "validating":
                saved.update(phase="failed", errorType=type(error).__name__, timestamp=datetime.now(timezone.utc).isoformat())
                write_atomic(status_file, json.dumps(saved) + "\n")
            raise


def _activate(tag, sha, root, school, week):
    home = Path.home()
    candidate = root / sha
    current = root / "current"
    state_file = root / "deployment-status.json"
    if candidate.is_symlink() or not candidate.is_dir() or state_file.is_symlink():
        raise ValueError("Unsafe component or state path")
    manifest = load_release(tag, sha)
    if json.loads((candidate / "deploy-manifest.json").read_text(encoding="utf-8")) != manifest:
        raise ValueError("Prepared manifest differs from published release")
    verify_candidate(candidate, manifest)
    if current.exists() and not current.is_symlink():
        raise ValueError("Component current is not a symlink")
    previous = os.readlink(current) if current.is_symlink() else None
    if previous is not None and (Path(previous).parent != root or not HEX40.fullmatch(Path(previous).name)):
        raise ValueError("Unexpected previous component target")
    old_sha = installed_sha(root, home)
    targets = [home / ".config/systemd/user/opencigan-internal.service.d/10-pycomcigan.conf",
               home / ".config/systemd/user/opensigan.service.d/10-pycomcigan.conf"]
    snapshots = {}
    for target in targets:
        if target.is_symlink():
            raise ValueError("Unsafe systemd drop-in")
        snapshots[target] = target.read_text(encoding="utf-8") if target.exists() else None
    token_path = home / ".config/opencigan/internal.env"
    token_lines = token_path.read_text(encoding="utf-8").splitlines()
    tokens = [line.split("=", 1)[1] for line in token_lines if line.startswith("OPENCIGAN_INTERNAL_TOKEN=")]
    if len(tokens) != 1 or not tokens[0]:
        raise ValueError("Internal token configuration invalid")
    token = tokens[0]
    key = home / ".ssh/opencigan-pin-sync"
    if key.is_symlink() or not key.is_file() or key.stat().st_mode & 0o077:
        raise ValueError("Pin synchronization key unavailable or unsafe")
    state = {"requestedSha": sha, "activeSha": old_sha, "success": False,
             "verification": {"release": True, "package": True, "internal": False, "public": False},
             "rollback": False, "pinSync": "pending", "phase": "activating", "timestamp": datetime.now(timezone.utc).isoformat()}
    switched = False
    try:
        link = root / (".current-" + str(os.getpid()))
        link.symlink_to(candidate, target_is_directory=True)
        os.replace(link, current)
        switched = True
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_atomic(target, "[Service]\nEnvironment=PYTHONPATH=" + str(current) + "\nEnvironment=PYTHONDONTWRITEBYTECODE=1\n")
        systemctl("daemon-reload")
        systemctl("restart", "opencigan-internal.service")
        wait_ready(8001, "/internal/v1/timetable", 401)
        probe(8001, "/internal/v1/timetable", {"school": school, "week": week}, token)
        state["verification"]["internal"] = True
        systemctl("restart", "opensigan.service")
        wait_ready(8000, "/api/v1/status", 200)
        probe(8000, "/api/v1/timetable", {"school": school, "week": week})
        state["verification"]["public"] = True
        state.update(activeSha=sha, success=True)
    except BaseException:
        if switched:
            if previous:
                link = root / (".rollback-" + str(os.getpid()))
                link.symlink_to(previous, target_is_directory=True)
                os.replace(link, current)
            else:
                current.unlink(missing_ok=True)
            for target, old in snapshots.items():
                if old is None:
                    target.unlink(missing_ok=True)
                else:
                    write_atomic(target, old)
            errors = []
            for args in (("daemon-reload",), ("restart", "opencigan-internal.service")):
                try:
                    systemctl(*args)
                except Exception as error:
                    errors.append(type(error).__name__)
            try:
                wait_ready(8001, "/internal/v1/timetable", 401)
                probe(8001, "/internal/v1/timetable", {"school": school, "week": week}, token)
            except Exception as error:
                errors.append(type(error).__name__)
            try:
                systemctl("restart", "opensigan.service")
                wait_ready(8000, "/api/v1/status", 200)
                probe(8000, "/api/v1/timetable", {"school": school, "week": week})
            except Exception as error:
                errors.append(type(error).__name__)
            state["rollback"] = not errors
            if errors:
                state["rollbackErrors"] = errors
        state["phase"] = "activation_failed"
        raise
    finally:
        state["timestamp"] = datetime.now(timezone.utc).isoformat()
        write_atomic(state_file, json.dumps(state, ensure_ascii=False) + "\n")
    try:
        state["pinSync"] = sync(sha, key)
    except Exception:
        state["pinSync"] = "failed"
        state["phase"] = "pin_sync_failed"
        state["timestamp"] = datetime.now(timezone.utc).isoformat()
        write_atomic(state_file, json.dumps(state, ensure_ascii=False) + "\n")
        raise
    state["phase"] = "complete"
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    write_atomic(state_file, json.dumps(state, ensure_ascii=False) + "\n")
    return state


def retry_pin(root):
    import fcntl
    root = Path(root).resolve(strict=True)
    lock = root / ".deploy.lock"
    status_file = root / "deployment-status.json"
    current = root / "current"
    if lock.is_symlink() or status_file.is_symlink() or not current.is_symlink():
        raise ValueError("Unsafe synchronization state")
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(status_file.read_text(encoding="utf-8"))
        target = Path(os.readlink(current))
        sha = state.get("activeSha", "")
        if (target.parent != root or target.name != sha or not HEX40.fullmatch(sha)
                or not state.get("success") or not state.get("verification", {}).get("internal")
                or not state.get("verification", {}).get("public")):
            raise ValueError("Active component was not verified")
        try:
            state["pinSync"] = sync(sha, Path.home() / ".ssh/opencigan-pin-sync")
            state["phase"] = "complete"
        except Exception:
            state["pinSync"] = "failed"
            state["phase"] = "pin_sync_failed"
            raise
        finally:
            state["timestamp"] = datetime.now(timezone.utc).isoformat()
            write_atomic(status_file, json.dumps(state, ensure_ascii=False) + "\n")
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--sha")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--school")
    parser.add_argument("--week")
    parser.add_argument("--retry-pin", action="store_true")
    args = parser.parse_args()
    if args.retry_pin:
        if any((args.tag, args.sha, args.school, args.week)):
            parser.error("--retry-pin cannot be combined with deployment arguments")
        result = retry_pin(args.root)
    else:
        if not all((args.tag, args.sha, args.school, args.week)):
            parser.error("--tag, --sha, --school and --week are required")
        result = activate(args.tag, args.sha, args.root, args.school, args.week)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
