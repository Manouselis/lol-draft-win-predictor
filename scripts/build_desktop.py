"""Build an explicit, secret-free Windows distribution. Run in an isolated build venv."""
import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import zipfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build = ROOT.parent / "desktop-build"
    build.mkdir(exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
                    "--name", "LeagueDraftLab", "--paths", str(ROOT / "backend"),
                    "--add-data", str(ROOT / "frontend/dist") + ":frontend/dist",
                    "--add-data", str(ROOT / "tests/fixtures") + ":tests/fixtures",
                    "--collect-submodules", "loldraft", "--collect-submodules", "uvicorn",
                    "--exclude-module", "pytest", "--exclude-module", "pip_audit",
                    "--exclude-module", "PyInstaller", "--exclude-module", "pip",
                    "--distpath", str(build / "dist"), "--workpath", str(build / "work"),
                    "--specpath", str(build), str(ROOT / "scripts/desktop_entry.py")], check=True, cwd=ROOT)
    bundle = build / "dist/LeagueDraftLab"
    (bundle / "LICENSE.txt").write_bytes((ROOT / "LICENSE").read_bytes())
    notices = []
    names = [line.split("==")[0] for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines() if "==" in line]
    names.append("pyinstaller")
    for name in names:
        dist = importlib.metadata.distribution(name)
        notices.append(f"\n{name} {dist.version}\n")
        for file in dist.files or []:
            if ".dist-info" in str(file) and any(word in str(file).lower() for word in ("license", "copying", "notice")):
                path = Path(dist.locate_file(file))
                if path.is_file():
                    notices.append(path.read_text(encoding="utf-8", errors="replace"))
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        notices.append(python_license.read_text(encoding="utf-8", errors="replace"))
    (bundle / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(notices), encoding="utf-8")
    inputs = sorted([*ROOT.glob("backend/loldraft/*.py"), *ROOT.glob("frontend/dist/**/*"),
                     ROOT / "requirements.lock", ROOT / "scripts/desktop_entry.py"])
    manifest = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in inputs if path.is_file()}
    (bundle / "BUILD-INFO.json").write_text(json.dumps({"version": VERSION, "inputs": manifest}, indent=2), encoding="utf-8")
    (bundle / "READ-ME.txt").write_text(
        f"League Draft Lab {VERSION}\n\nExtract the whole folder, then double-click LeagueDraftLab.exe.\n"
        "No Python, Node, administrator access, or installer is required.\n"
        "First use: Settings -> Connect Riot -> Validate key & start collecting.\n"
        "Keep the folder together: _internal contains the runtime.\n"
        "The browser shows the match database and private key file paths in Settings.\n"
        "The app needs an awake PC, Internet, a running collector and a valid key.\n"
        "It does not start automatically when Windows boots.\n"
        "Settings -> Quit app & save progress closes the background server.\n"
        "Live predictions remain disabled pending Riot review.\n"
        "This prototype does not include a key, match dataset, or trained model.\n", encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.write(path, str(path.relative_to(bundle.parent)))
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".zip.sha256").write_text(digest + "  " + args.output.name + "\n", encoding="utf-8")
    print(json.dumps({"archive": str(args.output), "sha256": digest, "bytes": args.output.stat().st_size}))


if __name__ == "__main__":
    main()
