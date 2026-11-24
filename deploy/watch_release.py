"""Poll the fork's published release and deploy only through the verified path."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from deploy.fork_manifest import HEX40, TAG, api, load_release
from deploy.release_deploy import deploy, retry_pending_pin


def latest_release():
    release = api("releases/latest")
    tag = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease") or not TAG.fullmatch(tag):
        raise ValueError("Latest release is not a published stable release")
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
    load_release(tag, sha)
    return tag, sha


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
        if status.is_file():
            state = json.loads(status.read_text(encoding="utf-8"))
            if state.get("success") and state.get("pinSync") in ("pending", "failed"):
                return retry_pending_pin(root)
        tag, sha = latest_release()
        return deploy(tag, sha, root, release, school, week)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--school", required=True)
    args = parser.parse_args()
    today = datetime.now(timezone(timedelta(hours=9))).date()
    week = (today - timedelta(days=today.weekday())).isoformat()
    print(json.dumps(poll(args.root, args.release, args.school, week)))


if __name__ == "__main__":
    main()
