"""Validate the project fork's release manifest and package files."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

REPOSITORY = "Transient-Onlooker/pycomcigan"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,99}\Z")
FILENAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.py\Z")
VERSION = re.compile(r"[0-9][A-Za-z0-9.+_-]{0,63}\Z")


def fetch(url, limit):
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "opencigan-deployer"})
    with urlopen(request, timeout=20) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("GitHub response exceeds size limit")
    return data


def api(path):
    return json.loads(fetch("https://api.github.com/repos/" + REPOSITORY + "/" + path, 1024 * 1024))


def validate_manifest(manifest, tag, commit):
    if (not isinstance(manifest, dict) or manifest.get("git_sha") != commit
            or manifest.get("origin") not in ("upstream", "custom", "fork", "patched")
            or not isinstance(manifest.get("version"), str) or not VERSION.fullmatch(manifest["version"])):
        raise ValueError("Release manifest identity mismatch")
    legacy = manifest.get("repo") == REPOSITORY and manifest.get("tag") == tag
    current = ("repo" not in manifest and "tag" not in manifest
               and manifest.get("name") == "pycomcigan" and manifest["version"] == tag)
    if not (legacy or current):
        raise ValueError("Release manifest identity mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Release manifest file list missing")
    if current:
        if any(not isinstance(name, str) or not name.startswith("pycomcigan/") for name in files):
            raise ValueError("Release manifest contains invalid file paths")
        files = {name.removeprefix("pycomcigan/"): digest for name, digest in files.items()}
    if "__init__.py" not in files:
        raise ValueError("Release manifest file list missing")
    if any(not isinstance(name, str) or not FILENAME.fullmatch(name)
           or not isinstance(digest, str) or not HEX64.fullmatch(digest)
           for name, digest in files.items()):
        raise ValueError("Release manifest contains invalid file hashes")
    return files


def load_release(tag, requested_sha):
    if not TAG.fullmatch(tag) or not HEX40.fullmatch(requested_sha):
        raise ValueError("Invalid tag or requested SHA")
    release = api("releases/tags/" + quote(tag, safe=""))
    if release.get("draft") or release.get("tag_name") != tag:
        raise ValueError("Release is not published")
    obj = api("git/ref/tags/" + quote(tag, safe=""))["object"]
    for _ in range(4):
        if obj.get("type") != "tag":
            break
        sha = obj.get("sha", "")
        if not isinstance(sha, str) or not HEX40.fullmatch(sha):
            raise ValueError("Invalid annotated tag")
        obj = api("git/tags/" + sha)["object"]
    if obj.get("type") != "commit" or obj.get("sha") != requested_sha:
        raise ValueError("Release tag does not match requested SHA")
    assets = [a for a in release.get("assets", []) if a.get("name") == "deploy-manifest.json"]
    if len(assets) != 1 or assets[0].get("state") != "uploaded":
        raise ValueError("Release manifest asset missing or ambiguous")
    digest = assets[0].get("digest", "")
    if not digest.startswith("sha256:") or not HEX64.fullmatch(digest[7:]):
        raise ValueError("Release manifest digest missing")
    expected_url = "https://github.com/" + REPOSITORY + "/releases/download/" + quote(tag, safe="") + "/deploy-manifest.json"
    if assets[0].get("browser_download_url") != expected_url:
        raise ValueError("Unexpected manifest URL")
    content = fetch(expected_url, 65536)
    if hashlib.sha256(content).hexdigest() != digest[7:]:
        raise ValueError("Release manifest digest mismatch")
    manifest = json.loads(content)
    validate_manifest(manifest, tag, requested_sha)
    return manifest


def verify_package(directory, manifest):
    files = validate_manifest(manifest, manifest.get("tag", manifest["version"]), manifest["git_sha"])
    directory = Path(directory)
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file() or p.is_symlink()}
    if actual != set(files):
        raise ValueError("Package file list mismatch")
    for name, expected in files.items():
        path = directory / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Package file hash mismatch: " + name)


def verify_candidate(directory, manifest):
    directory = Path(directory)
    info_name = "pycomcigan-" + manifest["version"] + ".dist-info"
    if {p.name for p in directory.iterdir()} != {"pycomcigan", info_name, "deploy-manifest.json"}:
        raise ValueError("Unexpected component files")
    info = directory / info_name
    if info.is_symlink() or (directory / "pycomcigan").is_symlink() or (directory / "deploy-manifest.json").is_symlink():
        raise ValueError("Component symlinks are not allowed")
    if {p.name for p in info.iterdir()} != {"METADATA", "direct_url.json"}:
        raise ValueError("Unexpected component metadata files")
    if any(p.is_symlink() for p in info.iterdir()):
        raise ValueError("Component metadata symlinks are not allowed")
    metadata = "Metadata-Version: 2.1\nName: pycomcigan\nVersion: " + manifest["version"] + "\nRequires-Dist: pycryptodomex>=3.23,<4\n"
    direct = {"url": "https://github.com/Transient-Onlooker/pycomcigan.git",
              "vcs_info": {"vcs": "git", "commit_id": manifest["git_sha"], "requested_revision": manifest["git_sha"]}}
    if (info / "METADATA").read_text(encoding="utf-8") != metadata or json.loads((info / "direct_url.json").read_text(encoding="utf-8")) != direct:
        raise ValueError("Component metadata mismatch")
    verify_package(directory / "pycomcigan", manifest)
