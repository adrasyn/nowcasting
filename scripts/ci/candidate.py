"""Fingerprint the one export shared by smoke, browser QA and Pages."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def inventory(directory):
    if not directory.is_dir():
        raise ValueError(f"Missing directory: {directory}")
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink in candidate: {path}")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise ValueError(f"Empty candidate directory: {directory}")
    return result


def digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_checkout(commit):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != commit:
        raise ValueError("Checked-out source differs from the candidate commit")


def validate_pages(site, commit):
    for name in ("index.html", "simple/index.html"):
        text = (site / name).read_text()
        if not re.search(r'<meta[^>]*name="build-commit"[^>]*content="' + re.escape(commit) + r'"', text):
            raise ValueError(f"{name} is not the candidate commit")


def create(site, fixtures, commit, run):
    validate_pages(site, commit)
    files = inventory(site)
    return {"version": 1, "commit": commit, "run_id": run,
            "files": files, "export_sha256": digest(files), "fixtures": inventory(fixtures)}


def verify(manifest, site, fixtures, commit, run):
    if manifest.get("version") != 1 or manifest.get("commit") != commit or manifest.get("run_id") != run:
        raise ValueError("Candidate identity/run differs; PR exports cannot stand in for production exports")
    validate_pages(site, commit)
    files = inventory(site)
    if files != manifest.get("files") or digest(files) != manifest.get("export_sha256"):
        raise ValueError("Export changed after build/smoke or during artifact transfer")
    if inventory(fixtures) != manifest.get("fixtures"):
        raise ValueError("Browser fixtures do not match the guarded candidate")
    return {"commit": commit, "run_id": run, "files": len(files),
            "export_sha256": digest(files), "result": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["create", "verify"])
    parser.add_argument("--site", type=Path, default=Path("out"))
    parser.add_argument("--fixtures", type=Path, default=Path("ci-artifact/fixtures"))
    parser.add_argument("--manifest", type=Path, default=Path("ci-artifact/manifest.json"))
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    validate_checkout(args.commit)
    if args.operation == "create":
        result = create(args.site, args.fixtures, args.commit, args.run)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: result[k] for k in ("commit", "run_id", "export_sha256")}))
    else:
        print(json.dumps(verify(json.loads(args.manifest.read_text()), args.site, args.fixtures, args.commit, args.run)))
