"""Fail closed on credential patterns or private artifacts. Never print matched values."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile(rb"RGAPI-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"),
    re.compile(rb"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})(?![A-Za-z0-9_])"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def private_file(name):
    path = PurePosixPath(name.replace("\\", "/"))
    if path.name == ".env.example":
        return False
    return (path.name == ".env" or path.name.startswith(".env.") or
            re.search(r"\.(?:sqlite\w*|joblib|pkl|log|zip|7z)$", path.name) is not None or
            path.name in ("lockfile", "collection.lock", "training.lock") or
            any(part in ("data", "models", "logs", ".venv", "node_modules") for part in path.parts[:-1]))


def contains_secret(data):
    return any(pattern.search(data) for pattern in PATTERNS)


def scan(root=ROOT, *, staged=False, history=False, archive=None):
    git = os.getenv("GIT_EXE") or shutil.which("git")
    findings, checked = [], 0
    def command(*args):
        return subprocess.check_output([git, "-C", str(root), *args])
    if archive:
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                if entry.is_dir():
                    continue
                checked += 1
                # Vendor libraries can have their own data directories. Private runtime
                # files may never appear beside the executable or in the source archive.
                parts = PurePosixPath(entry.filename).parts
                bundled_library = "_internal" in parts
                if ((private_file(entry.filename) and not bundled_library) or
                        contains_secret(package.read(entry))):
                    findings.append(entry.filename)
        return checked, findings
    if not git:
        raise RuntimeError("Git is required for the source security check")
    names = command("diff", "--cached", "--name-only", "--diff-filter=ACM", "-z") if staged else command("ls-files", "-z")
    for raw in names.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = root / name
        if not staged and not path.is_file():
            continue
        data = command("show", ":" + name) if staged else path.read_bytes()
        checked += 1
        if private_file(name) or contains_secret(data):
            findings.append(name)
    if history:
        objects = command("rev-list", "--objects", "--all").decode("utf-8").splitlines()
        process = subprocess.Popen([git, "-C", str(root), "cat-file", "--batch"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for line in objects:
                oid, _, name = line.partition(" ")
                process.stdin.write((oid + "\n").encode())
                process.stdin.flush()
                header = process.stdout.readline().split()
                data = process.stdout.read(int(header[2]))
                process.stdout.read(1)
                checked += 1
                if (header[1] in (b"blob", b"commit", b"tag") and contains_secret(data)) or (name and private_file(name)):
                    findings.append((name or "Git object") + " @ " + oid[:12])
        finally:
            process.stdin.close()
            process.stdout.close()
            process.wait()
    return checked, sorted(set(findings))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    checked, findings = scan(staged=args.staged, history=args.history, archive=args.archive)
    if findings:
        for name in findings:
            print("Blocked private artifact or credential pattern: " + name)
        raise SystemExit(1)
    print(f"Secret/artifact scan passed: {checked} files/objects; matched values are never printed.")


if __name__ == "__main__":
    main()
