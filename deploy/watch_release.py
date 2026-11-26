"""Poll the fork's published release and deploy only through the verified path."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from packaging.version import InvalidVersion, Version

from deploy.fork_manifest import HEX40, TAG, api, load_release
from deploy.release_deploy import deploy, retry_pending_pin


def latest_release():
    candidates = []
    page = 1
    while True:
        releases = api(f"releases?per_page=100&page={page}")
        if not isinstance(releases, list):
            raise ValueError("Invalid release list")
        for release in releases:
            tag = release.get("tag_name", "")
            if release.get("draft") or release.get("prerelease") or not isinstance(tag, str) or not TAG.fullmatch(tag):
                continue
            try:
                version = Version(tag)
            except InvalidVersion:
                continue
            if not version.is_prerelease and not version.is_devrelease:
                candidates.append((version, tag))
        if len(releases) < 100:
            break
        page += 1
    if not candidates:
        raise ValueError("No published stable release")
    highest = max(version for version, _ in candidates)
    selected = []
    for version, tag in candidates:
        if version != highest:
            continue
        sha = resolve_release(tag)
        selected.append((tag, sha))
    if len({sha for _, sha in selected}) != 1:
        raise ValueError("Conflicting release commits for the same version")
    return selected[0]


def resolve_release(tag):
    obj = api("git/ref/tags/" + quote(tag, safe=""))["object"]
    for _ in range(4):
        if obj.get("type") != "tag":
            break
        sha = obj.get("sha", "")
        if not HEX40.fullmatch(sha):
            raise ValueError("Invalid annotated tag")
        obj = api("git/tags/" + sha)["object"]
    sha = obj.get("sha", "")
    if obj.get("type") != "commit" or not HEX40.fullmatch(sha):
        raise ValueError("Invalid release commit")
    manifest = load_release(tag, sha)
    if Version(manifest["version"]) != Version(tag):
        raise ValueError("Release tag and manifest version differ")
    return sha


def poll(root, release, school, week):
    import fcntl

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root.resolve(strict=True)
    lock = root / ".watch.lock"
    status = root / "deployment-status.json"
    if lock.is_symlink() or status.is_symlink():
        raise ValueError("Unsafe watcher state")
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = {}
        if status.is_file():
            state = json.loads(status.read_text(encoding="utf-8"))
        pending = state.get("success") and state.get("pinSync") in ("pending", "failed")
        try:
            tag, sha = latest_release()
        except Exception:
            if pending:
                try:
                    retry_pending_pin(root)
                except Exception:
                    pass
            raise
        failed = state.get("lastAttempt", state)
        if failed.get("requestedSha") == sha and failed.get("phase") == "activation_failed":
            if pending:
                return retry_pending_pin(root)
            return {"skipped": True, "reason": "previous_activation_failed", "requestedSha": sha}
        if pending and state.get("activeSha") == sha:
            return retry_pending_pin(root)
        try:
            return deploy(tag, sha, root, release, school, week, automatic=True)
        except Exception:
            if pending and status.is_file():
                current = json.loads(status.read_text(encoding="utf-8"))
                if current.get("success") and current.get("pinSync") in ("pending", "failed"):
                    try:
                        retry_pending_pin(root)
                    except Exception:
                        pass
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--school", required=True)
    args = parser.parse_args()
    today = datetime.now(timezone(timedelta(hours=9))).date()
    week = (today - timedelta(days=today.weekday())).isoformat()
    try:
        result = poll(args.root, args.release, args.school, week)
    except BlockingIOError:
        result = {"skipped": True, "reason": "deployment_locked"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
