"""Prepare, validate and activate one explicitly requested fork release."""
import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from deploy.activate_component import activate, installed_sha, retry_pin, write_atomic
from deploy.fork_manifest import HEX40, TAG, load_release, validate_manifest
from deploy.prepare_component import prepare
from packaging.version import Version


def preserve_verified_after_failure(root, status, previous):
    if not previous.get("success"):
        return
    verification = previous.get("verification", {})
    if not verification.get("internal") or not verification.get("public"):
        return
    try:
        if installed_sha(root, Path.home()) != previous.get("activeSha"):
            return
        failure = json.loads(status.read_text(encoding="utf-8"))
        if failure.get("phase") == "activation_failed" and not failure.get("rollback"):
            return
        restored = {**previous, "lastAttempt": failure}
        write_atomic(status, json.dumps(restored) + "\n")
    except Exception:
        return


def deploy(tag, sha, root, release, school, week, *, automatic=False):
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
        previous = {}
        if status.is_file():
            previous = json.loads(status.read_text(encoding="utf-8"))
            verified = previous.get("verification", {})
            if (previous.get("activeSha") == sha and previous.get("success")
                    and verified.get("internal") and verified.get("public")
                    and installed_sha(root, Path.home()) == sha):
                if previous.get("pinSync") in ("pending", "failed"):
                    return retry_pin(root)
                return {**previous, "skipped": True}
        if automatic:
            active_sha = installed_sha(root, Path.home())
            verified = previous.get("verification", {})
            if (not previous.get("success") or previous.get("activeSha") != active_sha
                    or not verified.get("internal") or not verified.get("public")):
                raise ValueError("Active component deployment is not verified")
            component = root / active_sha
            manifest_path = component / "deploy-manifest.json"
            if component.is_symlink() or not component.is_dir() or manifest_path.is_symlink() or not manifest_path.is_file():
                raise ValueError("Active component manifest is missing")
            active = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = validate_manifest(active, active.get("tag", active.get("version", "")), active_sha)
            package = component / "pycomcigan"
            info = component / ("pycomcigan-" + active["version"] + ".dist-info")
            if package.is_symlink() or info.is_symlink() or not info.is_dir():
                raise ValueError("Unsafe active component metadata")
            metadata = (info / "METADATA").read_text(encoding="utf-8")
            expected_metadata = ("Metadata-Version: 2.1\nName: pycomcigan\nVersion: " + active["version"]
                                 + "\nRequires-Dist: pycryptodomex>=3.23,<4\n")
            direct = json.loads((info / "direct_url.json").read_text(encoding="utf-8"))
            if (metadata != expected_metadata or direct.get("url") != "https://github.com/Transient-Onlooker/pycomcigan.git"
                    or direct.get("vcs_info", {}).get("commit_id") != active_sha):
                raise ValueError("Active component metadata mismatch")
            if {p.name for p in package.glob("*.py")} != set(files):
                raise ValueError("Active component file list mismatch")
            for name, digest in files.items():
                path = package / name
                if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("Active component file hash mismatch")
            candidate = load_release(tag, sha)
            if Version(candidate["version"]) != Version(tag):
                raise ValueError("Release tag and manifest version differ")
            active_version, candidate_version = Version(active["version"]), Version(candidate["version"])
            if candidate_version < active_version or (candidate_version == active_version and sha != active_sha):
                if previous.get("pinSync") in ("pending", "failed"):
                    return retry_pin(root)
                return {"skipped": True, "reason": "older_release" if candidate_version < active_version else "version_sha_mismatch",
                        "requestedSha": sha, "activeSha": active_sha}
        try:
            if (root / sha).exists() or (root / sha).is_symlink():
                # Revalidate and retest even when a prior candidate is retained.
                with tempfile.TemporaryDirectory(prefix=".recheck-", dir=root) as temporary:
                    prepare(tag, sha, temporary, release, school, week)
            else:
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
            preserve_verified_after_failure(root, status, previous)
            raise
        try:
            return activate(tag, sha, root, school, week)
        except Exception:
            preserve_verified_after_failure(root, status, previous)
            raise


def retry_pending_pin(root):
    import fcntl

    root = Path(root).resolve(strict=True)
    lock = root / ".orchestration.lock"
    if lock.is_symlink():
        raise ValueError("Unsafe deployment lock")
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return retry_pin(root)


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
        result = retry_pending_pin(args.root)
    else:
        if not all((args.tag, args.sha, args.release, args.school, args.week)):
            parser.error("--tag, --sha, --release, --school and --week are required")
        result = deploy(args.tag, args.sha, args.root, args.release, args.school, args.week)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
