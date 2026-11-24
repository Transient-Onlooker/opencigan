"""Verify a pinned component manifest, GitHub release tag and wheel."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
OFFICIAL = "hegelty/pycomcigan"


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def github_json(path):
    request = Request("https://api.github.com/" + path,
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "opencigan-release-verifier"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def verify(manifest_path, manifest_sha256, wheel_path, allowed_repository):
    if not SHA256.fullmatch(manifest_sha256) or digest(manifest_path) != manifest_sha256:
        raise ValueError("Manifest digest mismatch")
    if manifest_path.stat().st_size > 65536:
        raise ValueError("Manifest too large")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo, tag = manifest.get("repository"), manifest.get("releaseTag")
    commit, wheel_hash = manifest.get("commit"), manifest.get("wheelSha256")
    kind = manifest.get("kind")
    if (manifest.get("schemaVersion") != 1 or not isinstance(repo, str)
            or not REPOSITORY.fullmatch(repo) or repo != allowed_repository
            or not isinstance(tag, str) or not TAG.fullmatch(tag) or '..' in tag
            or not isinstance(commit, str) or not COMMIT.fullmatch(commit)
            or not isinstance(wheel_hash, str) or not SHA256.fullmatch(wheel_hash)
            or kind not in ("official", "fork")
            or (repo.lower() == OFFICIAL) != (kind == "official")):
        raise ValueError("Invalid manifest or untrusted repository")
    if wheel_path.suffix != ".whl" or digest(wheel_path) != wheel_hash:
        raise ValueError("Wheel digest mismatch")
    prefix = "repos/" + repo + "/"
    release = github_json(prefix + "releases/tags/" + quote(tag, safe=""))
    if release.get("draft") or release.get("tag_name") != tag:
        raise ValueError("Release not published or tag mismatch")
    obj = github_json(prefix + "git/ref/tags/" + quote(tag, safe="/"))["object"]
    for _ in range(4):
        if obj.get("type") != "tag":
            break
        sha = obj.get("sha", "")
        if not isinstance(sha, str) or not COMMIT.fullmatch(sha):
            raise ValueError("Invalid annotated tag")
        obj = github_json(prefix + "git/tags/" + sha)["object"]
    if obj.get("type") != "commit" or obj.get("sha") != commit:
        raise ValueError("Release tag commit mismatch")
    return {"repository": repo, "kind": kind, "releaseTag": tag, "commit": commit,
            "wheelSha256": wheel_hash, "manifestSha256": manifest_sha256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--allowed-repository", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.manifest, args.manifest_sha256, args.wheel, args.allowed_repository)))


if __name__ == "__main__":
    main()
