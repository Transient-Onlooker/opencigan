"""Prepare, validate and activate one explicitly requested fork release."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from deploy.activate_component import activate, installed_sha, retry_pin, write_atomic
from deploy.fork_manifest import HEX40, TAG
from deploy.prepare_component import prepare


def deploy(tag, sha, root, release, school, week):
    import fcntl

    if not TAG.fullmatch(tag) or not HEX40.fullmatch(sha):
        raise ValueError("Invalid release tag or SHA")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root.resolve(strict=True)
    lock = root / ".orchestration.lock"
    status = root / "deployment-status.json"
    if lock.is_symlink() or status.is_symlink():
        raise ValueError("Unsafe deployment state path")
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            prepare(tag, sha, root, release, school, week)
        except Exception as error:
            try:
                active = installed_sha(root, Path.home())
            except Exception:
                active = None
            result = {"requestedSha": sha, "activeSha": active, "success": False,
                      "verification": {"prepare": False}, "rollback": False, "pinSync": "not_started",
                      "phase": "prepare_failed", "errorType": type(error).__name__,
                      "timestamp": datetime.now(timezone.utc).isoformat()}
            write_atomic(status, json.dumps(result) + "\n")
            raise
        return activate(tag, sha, root, school, week)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--sha")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--school")
    parser.add_argument("--week")
    parser.add_argument("--retry-pin", action="store_true")
    args = parser.parse_args()
    if args.retry_pin:
        if any((args.tag, args.sha, args.release, args.school, args.week)):
            parser.error("--retry-pin cannot be combined with deployment arguments")
        result = retry_pin(args.root)
    else:
        if not all((args.tag, args.sha, args.release, args.school, args.week)):
            parser.error("--tag, --sha, --release, --school and --week are required")
        result = deploy(args.tag, args.sha, args.root, args.release, args.school, args.week)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
