"""Prepare and validate a fork release without changing active services."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from deploy.fork_manifest import load_release, verify_candidate, verify_package


def run(command, **kwargs):
    subprocess.run(command, check=True, **kwargs)


def prepare(tag, sha, components, release, school, week):
    manifest = load_release(tag, sha)
    components = Path(components)
    release = Path(release).resolve(strict=True)
    python = release / ".venv/bin/python"
    if not python.is_file():
        raise ValueError("Active release venv missing")
    components.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = components / sha
    if destination.exists() or destination.is_symlink():
        raise ValueError("Component SHA already exists")
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=components) as temporary:
        root = Path(temporary)
        source, package = root / "source", root / "package"
        run(["git", "clone", "--quiet", "--no-checkout", "https://github.com/Transient-Onlooker/pycomcigan.git", str(source)])
        run(["git", "-C", str(source), "checkout", "--quiet", "--detach", sha])
        actual_sha = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if actual_sha != sha:
            raise ValueError("Source SHA mismatch")
        verify_package(source / "pycomcigan", manifest)
        if manifest.get("dependencies") != {"pycryptodomex": ">=3.23,<4"}:
            raise ValueError("Unsupported component dependencies")
        package.mkdir(mode=0o700)
        shutil.copytree(source / "pycomcigan", package / "pycomcigan")
        verify_package(package / "pycomcigan", manifest)
        info = package / ("pycomcigan-" + manifest["version"] + ".dist-info")
        info.mkdir(mode=0o700)
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: pycomcigan\nVersion: " + manifest["version"]
                                       + "\nRequires-Dist: pycryptodomex>=3.23,<4\n", encoding="utf-8")
        (info / "direct_url.json").write_text(json.dumps({"url": "https://github.com/Transient-Onlooker/pycomcigan.git",
            "vcs_info": {"vcs": "git", "commit_id": sha, "requested_revision": sha}}), encoding="utf-8")
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(package), "PYTHONDONTWRITEBYTECODE": "1",
                    "OPENCIGAN_COMCIGAN_PROXY": "http://127.0.0.1:18084"})
        run([str(python), "-m", "unittest", "tests.test_public_api", "tests.test_timetable_cache",
             "tests.test_comcigan_proxy", "tests.test_internal_api"], cwd=release, env=env)
        probe = ("import importlib.metadata as m,json,sys,pycomcigan; from pathlib import Path; "
                 "assert Path(pycomcigan.__file__).resolve().is_relative_to(Path(sys.argv[3]).resolve()); "
                 "assert json.loads(m.distribution('pycomcigan').read_text('direct_url.json'))['vcs_info']['commit_id']==sys.argv[4]; "
                 "from backend.timetable import fetch_timetable; "
                 "v=fetch_timetable(sys.argv[1],sys.argv[2],include_original=True); "
                 "assert v['schoolId']==sys.argv[1] and isinstance(v['records'],list) and not v['stale']; "
                 "assert all('originalSubject' in x and 'originalTeacher' in x for x in v['records']); "
                 "print(json.dumps({'records':len(v['records'])}))")
        run([str(python), "-c", probe, school, week, str(package), sha], cwd=release, env=env)
        (package / "deploy-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        verify_candidate(package, manifest)
        os.rename(package, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--components", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--school", required=True)
    parser.add_argument("--week", required=True)
    args = parser.parse_args()
    print(prepare(args.tag, args.sha, args.components, args.release, args.school, args.week))


if __name__ == "__main__":
    main()
