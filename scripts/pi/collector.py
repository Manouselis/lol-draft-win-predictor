"""Headless collector and private maintenance commands; no desktop/ML imports."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from loldraft.config import Config, private_state_dir  # noqa: E402
from loldraft.schemas import Settings  # noqa: E402
from loldraft.storage import Store  # noqa: E402


def backup_database(source, destination):
    """Snapshot SQLite including committed WAL changes; never copy a live database file."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError("Source database does not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
            with sqlite3.connect(destination) as snapshot:
                original.backup(snapshot)
                if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("Database snapshot failed its integrity check")
        destination.chmod(0o600)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def clock_synchronized():
    try:
        result = subprocess.run(["timedatectl", "show", "--property=NTPSynchronized", "--value"],
                                capture_output=True, text=True, timeout=5)
        return result.returncode == 0 and result.stdout.strip() == "yes"
    except (OSError, subprocess.TimeoutExpired):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=private_state_dir() / ".env")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="Collect only; systemd handles restart/retry")
    collect.add_argument("--wait-for-time", action="store_true")
    commands.add_parser("status", help="Show counts and safe status, never the API key")
    commands.add_parser("key", help="Validate and save a Riot key in private profile storage")
    backup = commands.add_parser("backup", help="Make a consistent SQLite snapshot without overwriting")
    backup.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = Config.load(env_file=args.env_file)
    config.data_dir = args.data_dir.resolve()
    if args.command == "backup":
        backup_database(config.data_dir / "matches.sqlite3", args.output)
        print("Consistent database snapshot saved; the source database was preserved.", flush=True)
        return 0
    store = Store(config.data_dir)
    settings = Settings.model_validate(store.get_meta("settings", {
        "region": config.region, "queue": config.queue, "target_matches": config.target_matches}))
    if args.command == "status":
        print(json.dumps({"database": str(store.path), "key_configured": bool(config.riot_key),
                          "dataset": store.stats(settings.region, settings.queue, settings.patches),
                          "collection": store.get_meta("collection")}, indent=2))
        return 0
    if args.command == "key":
        from loldraft.configuration import save_key, validate_key
        key = getpass.getpass("Riot key (hidden): ").strip()
        try:
            validate_key(key, settings.region)
            config.env_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            save_key(config, key)
        except (ValueError, OSError):
            print("Key was not saved. Check the key, network and private profile permissions.", flush=True)
            return 2
        print("Riot accepted the key. Saved privately; start or restart the collector service.", flush=True)
        return 0
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        signal.signal(getattr(signal, name), lambda *_: stop.set())
    if args.wait_for_time:
        print("Waiting for the Pi's network clock to synchronize before applying date filters.", flush=True)
        while not clock_synchronized():
            if stop.wait(10):
                return 0
    from loldraft.cli import run_collection
    try:
        run_collection(config, store, settings, stop=stop, auto_train=False)
    except RuntimeError:
        if stop.is_set():
            print("Collector stopped safely; download progress was saved.", flush=True)
            return 0
        print("Collection paused. Check status for the sanitized reason; the service retries in five minutes.",
              flush=True)
        return 2
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except (ValueError, OSError):
        print("Collector maintenance failed. Check the file paths, permissions and configuration; existing data was preserved.",
              file=sys.stderr, flush=True)
        result = 2
    raise SystemExit(result)
